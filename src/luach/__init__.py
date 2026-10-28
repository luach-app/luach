"""luach (לוח) — a household calendar run by an agent.

A FastAPI service that puts a governed tulip agent in front of one shared
Google Calendar. Every write the model proposes clears tulip's admission
gate first; the ones that matter hold for a person, and every decision
lands on a hash-chained audit trail.
"""

__version__ = "0.1.0"
