"""Application errors.

OrganizerError is the base; CancellationError is raised by JobContext.checkpoint()
when a run is cancelled, and every phase catches it separately so a cancel stops
the current game without aborting the whole run.
"""
class OrganizerError(Exception):
    """Base application error."""
class CancellationError(OrganizerError): pass

