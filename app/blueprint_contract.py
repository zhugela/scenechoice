"""The blueprint storage contract shared by the writer and the player.

``BLUEPRINT_VERSION`` describes the shape of the JSON this server writes into
SQL columns and expects to read back. It is deliberately not part of the
Pydantic schema: bumping a field name in the generation schema does not by
itself make stored archives unreadable, and adding a display-only validation
rule does not either. It is also not owned by any one service: the story store
writes and rebuilds that JSON, while the play engine checks the column before
touching the tree. Keeping the number here gives both modules one definition
without the play engine importing the storage service just for a constant.
"""

BLUEPRINT_VERSION = 1


def version_is_supported(stored: int) -> bool:
    """Whether a stored archive was written by the contract this server reads.

    The comparison has exactly one definition, here, and both entry points use
    it: :func:`app.services.story_store.load_blueprint` (the detail gate) and
    :func:`app.services.play_engine.advance_story` (the play gate). Each layer
    keeps its own exception type; only the comparison is shared.
    """
    return stored == BLUEPRINT_VERSION
