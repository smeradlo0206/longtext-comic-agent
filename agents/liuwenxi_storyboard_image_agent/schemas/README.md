# Schema boundary

The only upstream task request contract is:

- `upstream-scene-envelope-v1.schema.json` (`UpstreamSceneEnvelopeV1`)

The public asynchronous result contract is:

- `scene-result-v1.schema.json` (`SceneResultV1`)

All other schemas in this directory describe internal planning, compilation,
generation, or legacy single-image structures. They are versioned to keep the
pipeline deterministic and testable, but upstream callers must not submit them
to `POST /v1/scene-jobs`.
