"""Small exception module to avoid circular imports with the file memory store."""


class RevisionConflict(ValueError):
    """A caller wrote against an outdated revision."""
