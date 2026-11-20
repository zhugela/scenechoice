"""Translate play-engine failures into SceneChoice's public error contract.

Same rule as :mod:`app.services.provider_errors`: the mapping lives in the
service layer because it is product policy — which status and application code
we expose for a given failure. :mod:`app.services.play_engine` stays unaware of
HTTP, and the **play-specific** codes below appear in no other module, so the
route and its OpenAPI description cannot drift apart.

``40401`` is deliberately *not* owned here: it is the existing "story not found"
code already returned by ``app/api/stories.py``. Converging that literal is a
separate change (recorded in ``docs/harness/progress.md`` as next-batch work).
"""

from app.errors import AppError
from app.services.play_engine import (
    ChoiceNotInCurrentEpisode,
    NoMatchingEnding,
    PlayError,
    StoryFinished,
    StoryNotFound,
)

# OpenAPI descriptions live next to the mapping for the same reason they do in
# ``provider_errors``: the documented code and the returned code are one fact.
PLAY_400_DESCRIPTION = (
    "The submitted choice does not belong to the episode being played (40001)"
)
PLAY_404_DESCRIPTION = "Story not found (40401)"
PLAY_409_DESCRIPTION = "The story has already finished (40901)"
PLAY_500_DESCRIPTION = (
    "No ending matches the final metric state (50001); the archive was changed outside the API"
)


def play_error_to_app_error(exc: PlayError) -> AppError:
    """Return the application error that should surface for a play failure.

    Callers must use ``raise play_error_to_app_error(exc) from exc`` so the
    original engine error stays attached as ``__cause__``.
    """
    if isinstance(exc, StoryNotFound):
        return AppError("story not found", code=40401, status_code=404)
    if isinstance(exc, StoryFinished):
        return AppError("story has already finished", code=40901, status_code=409)
    if isinstance(exc, ChoiceNotInCurrentEpisode):
        return AppError(
            "choice does not belong to the episode being played",
            code=40001,
            status_code=400,
        )
    if isinstance(exc, NoMatchingEnding):
        # The blueprint passed reachability validation, so this means the
        # archive was changed outside the API: a server-side fault, not the
        # player's mistake. Do not pretend it is a 4xx.
        return AppError(
            "no ending matches the final metric state",
            code=50001,
            status_code=500,
        )
    # Defensive net for a future PlayError subclass. Unreachable today (the
    # engine raises only the four subclasses above), so it is deliberately not
    # advertised in PLAY_500_DESCRIPTION.
    return AppError("story could not be advanced", code=50002, status_code=500)
