"""Deterministic handoff from storyboard proposals to the local FLUX.2 workflow."""

from __future__ import annotations

from comic_agent.schemas.comic_production import (
    ComicProductionManifestV1,
    ComicProductionRequestV1,
    ComicStoryboardProposalV1,
    IdentityAnchorMode,
)
from comic_agent.schemas.image_workflow import (
    ContactSheetSettings,
    IdentityAnchorSpec,
    Shot,
    ShotReference,
    WorkflowJob,
)
from comic_agent.schemas.production import PromptSpecV1
from comic_agent.schemas.source import ProjectSpecV1
from comic_agent.schemas.visual import PanelTextOverlayV1
from comic_agent.services.context_builder import AgentContext
from comic_agent.services.id_service import checksum_text, stable_id
from comic_agent.services.visual_prompt_text import visual_expression_without_overlay_text
from flux2_agent.planning import compile_prompt


class LongTextComicCompiler:
    """Validate and compile one proposal into a provider-specific immutable manifest."""

    provider_name = "local-flux2-klein"
    compiler_id = "longtext-comic-compiler-v11"

    def compile(
        self,
        *,
        project: ProjectSpecV1,
        request: ComicProductionRequestV1,
        context: AgentContext,
        proposal: ComicStoryboardProposalV1,
    ) -> ComicProductionManifestV1:
        if project.id != context.project_id or proposal.project_id != project.id:
            raise ValueError("project, context, and storyboard proposal must match")
        if proposal.document_id != request.document_id:
            raise ValueError("storyboard proposal document does not match request")
        request_hash = checksum_text(
            f"{proposal.planner_id}\n{self.compiler_id}\n{request.model_dump_json()}"
        )
        run_id = stable_id("comicrun", project.id, request.document_id, request_hash)

        identity_anchors: list[IdentityAnchorSpec] = []
        if request.identity_anchor_mode == IdentityAnchorMode.AUTO:
            anchored_entities: set[str] = set()
            short_side = min(request.generation.width, request.generation.height)
            long_side = max(request.generation.width, request.generation.height)
            for asset in request.selected_assets:
                if asset.role not in {"character_identity", "character_outfit"}:
                    continue
                if asset.entity_id in anchored_entities:
                    continue
                anchored_entities.add(asset.entity_id)
                identity_anchors.append(
                    IdentityAnchorSpec(
                        anchor_id=stable_id("anchor", run_id, asset.entity_id),
                        slot=asset.slot,
                        asset_id=asset.asset_id,
                        entity_id=asset.entity_id,
                        description=asset.description,
                        display_name=asset.display_name,
                        seed=(request.generation.seed + 10000 + len(identity_anchors))
                        % (2**63),
                        width=min(768, short_side),
                        height=min(1024, long_side),
                    )
                )

        shots: list[Shot] = []
        seeds_by_panel_id: dict[str, int] = {}
        active_scene_asset_ids: set[str] = set()
        scene_assets = [asset for asset in request.selected_assets if asset.role == "scene"]
        for index, item in enumerate(proposal.panels):
            bound_entities = set(item.panel.character_bindings.values())
            searchable_visual_facts = "\n".join(
                [item.source_quote, item.visual_expression, *item.panel.must_show]
            )
            for asset in request.selected_assets:
                if (
                    asset.role == "scene"
                    and asset.display_name
                    and asset.display_name in searchable_visual_facts
                ):
                    active_scene_asset_ids = {asset.asset_id}
            if not active_scene_asset_ids and len(scene_assets) == 1:
                active_scene_asset_ids = {scene_assets[0].asset_id}
            selected_for_panel = [
                asset
                for asset in request.selected_assets
                if (
                    asset.role in {"character_identity", "character_outfit"}
                    and asset.entity_id in bound_entities
                )
                or asset.role == "style"
                or (
                    asset.role == "scene"
                    and asset.asset_id in active_scene_asset_ids
                )
                or (
                    asset.role in {"prop", "composition"}
                    and asset.display_name is not None
                    and asset.display_name in searchable_visual_facts
                )
            ]
            cast_names = list(
                dict.fromkeys(
                    asset.display_name or asset.entity_id
                    for asset in selected_for_panel
                    if asset.role in {"character_identity", "character_outfit"}
                )
            )
            cast_instruction = (
                f"当前画面恰好表现 {len(cast_names)} 名不同角色："
                + "、".join(cast_names)
                + "。人物数量必须与名单一致。"
                if cast_names
                else "当前画面的人物只依据当前原文。"
            )
            text_safe_instruction = self._text_safe_instruction(
                item.panel.text_overlays
            )
            visual_expression = visual_expression_without_overlay_text(
                item.visual_expression,
                item.panel.text_overlays,
            )
            references = [
                ShotReference(
                    slot=asset.slot,
                    asset_id=asset.asset_id,
                    role=asset.role,
                    purpose=asset.description,
                )
                for asset in selected_for_panel
            ]
            seed_parent_id = item.continuity_parent_panel_id
            uses_normalized_identity = (
                request.identity_anchor_mode == IdentityAnchorMode.AUTO
            )
            seed = (request.generation.seed + index) % (2**63)
            if seed_parent_id is not None and not uses_normalized_identity:
                seed = seeds_by_panel_id[seed_parent_id]
            seeds_by_panel_id[item.panel.panel_id] = seed
            image_parent_id = (
                seed_parent_id
                if len(bound_entities) >= 2 and not uses_normalized_identity
                else None
            )
            shots.append(
                Shot(
                    shot_id=item.panel.panel_id,
                    prompt=(
                        f"景别：{item.panel.shot_type}。机位：{item.panel.camera_angle}。"
                        f"{cast_instruction}{text_safe_instruction}{visual_expression}"
                    ),
                    references=references,
                    continuity_from=image_parent_id,
                    seed=seed,
                )
            )
        source_script = "\n\n".join(item.source_quote for item in proposal.panels)[:120000]
        job = WorkflowJob(
            job_id=run_id,
            source_script=source_script,
            comic_style=request.comic_style,
            global_prompt=request.global_prompt,
            quality_constraints=request.quality_constraints,
            selected_assets=request.selected_assets,
            reference_policy=request.reference_policy,
            generation=request.generation,
            visual_qa=request.visual_qa,
            identity_anchors=identity_anchors,
            contact_sheet=ContactSheetSettings(
                columns=request.panels_per_page,
                filename="chapter-overview.png",
            ),
            shots=shots,
        )
        anchor_id_by_asset_id = {
            anchor.asset_id: anchor.anchor_id for anchor in identity_anchors
        }
        prompts = [
            PromptSpecV1(
                prompt_id=stable_id("prompt", proposal.proposal_id, item.panel.panel_id),
                panel_id=item.panel.panel_id,
                provider=self.provider_name,
                model_name=request.generation.model_id,
                provider_prompt=compile_prompt(job, index),
                provider_options={
                    "width": request.generation.width,
                    "height": request.generation.height,
                    "steps": request.generation.steps,
                    "guidance_scale": request.generation.guidance_scale,
                    "seed": shots[index].seed,
                    "asset_ids": [reference.asset_id for reference in shots[index].references],
                    "identity_anchor_ids": [
                        anchor_id_by_asset_id[reference.asset_id]
                        for reference in shots[index].references
                        if reference.asset_id in anchor_id_by_asset_id
                    ],
                    "continuity_from": shots[index].continuity_from,
                    "seed_lineage_from": (
                        item.continuity_parent_panel_id
                        if request.identity_anchor_mode == IdentityAnchorMode.OFF
                        else None
                    ),
                    "continuity_keyframe_from": item.continuity_parent_panel_id,
                },
            )
            for index, item in enumerate(proposal.panels)
        ]
        return ComicProductionManifestV1(
            run_id=run_id,
            project_id=project.id,
            request_hash=request_hash,
            request=request,
            proposal=proposal,
            prompt_specs=prompts,
            workflow_job=job,
        )

    @staticmethod
    def _text_safe_instruction(overlays: list[PanelTextOverlayV1]) -> str:
        if not overlays:
            return ""
        labels = {
            "top_left": "左上",
            "top_right": "右上",
            "bottom_left": "左下",
            "bottom_right": "右下",
        }
        regions = "、".join(
            dict.fromkeys(labels[overlay.preferred_region] for overlay in overlays)
        )
        return (
            f"构图要求：画面{regions}使用与环境连续的开阔天空、素净墙面或柔和景深，"
            "人物面部与关键动作集中在画面中部。"
        )
