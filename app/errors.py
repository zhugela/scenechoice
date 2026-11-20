"""SceneChoice's shared business error codes.

Codes follow ``HTTP status x 100 + sequence`` (for example ``40902`` is
``409`` with sequence ``02``), so a code can be read as an HTTP status without
looking at the mapping module.
"""


class AppError(Exception):
    """可安全返回给客户端的业务异常。"""

    def __init__(self, message: str, *, code: int, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


# The story archive does not exist.
STORY_NOT_FOUND = 40401

# The submitted choice does not belong to the episode being played.
PLAY_CHOICE_NOT_IN_EPISODE = 40001

# The story has already reached an ending and accepts no further choices.
STORY_FINISHED = 40901

# The stored archive was produced by a blueprint contract this server does not
# support. The request is valid, so this is a conflict rather than a 4xx input
# error.
STORY_VERSION_UNSUPPORTED = 40902

# The blueprint passed reachability validation, so an unmatched end state means
# the archive was changed outside the API: a server-side fault.
NO_MATCHING_ENDING = 50001

# Defensive net for a future play-engine failure without a specific mapping.
PLAY_ADVANCE_FALLBACK = 50002

# Stored JSON columns cannot be rebuilt into a blueprint. Only a write outside
# the API can cause this, so it is a server-side fault.
STORY_ARCHIVE_CORRUPTED = 50003
