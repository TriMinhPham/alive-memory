"""bus_types.py — Topic constants for the in-process event bus."""

# Scene state pushed to web viewers after each cognitive cycle
TOPIC_SCENE_UPDATE = 'outbound.scene_update'

# Pipeline stage progress (fired by _emit_stage)
TOPIC_STAGE_PROGRESS = 'stage.progress'

# Full cycle log emitted after each completed cycle
TOPIC_CYCLE_COMPLETE = 'cycle.complete'
