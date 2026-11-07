class AppError(Exception):
    """可安全返回给客户端的业务异常。"""

    def __init__(self, message: str, *, code: int, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
