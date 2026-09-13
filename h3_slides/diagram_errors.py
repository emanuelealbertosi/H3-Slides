"""Structured renderer failures shared across the isolated Manim process."""


class DiagramLayoutError(ValueError):
    def __init__(self, message, location=(), code="text_space"):
        super().__init__(message)
        self.location, self.code = tuple(location), code

    def errors(self, **_kwargs):
        return [{"loc": self.location, "type": self.code, "msg": str(self)}]


class DiagramRenderError(ValueError):
    def __init__(self, message, issues):
        super().__init__(message)
        self.issues = issues

    def errors(self, **_kwargs):
        return self.issues
