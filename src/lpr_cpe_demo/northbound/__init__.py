"""Northbound message contracts for NXT, CPE, WFM and jTrack.

Provenance, stated per system because two of the four are guesses
-----------------------------------------------------------------
====================  ==========  =====================================
System                Provenance  Basis
====================  ==========  =====================================
CPE telemetry         STANDARD    TR-181 Device Data Model parameter
                                  paths, delivered over TR-369 (USP)
                                  Notify; DOCSIS counters use the
                                  CM-SP-CM-OSSI MIB object names
jTrack tickets        STANDARD    TM Forum TMF621 Trouble Ticket
                                  Management, Apache 2.0
WFM work orders       STANDARD    TM Forum TMF697 Work Order Management
NXT assurance         MODELLED    **The actual schema is unknown to me.**
                                  Shaped as a service-assurance snapshot
                                  because that is what the evidence refs
                                  in the existing scenarios imply. Treat
                                  every field name as a placeholder.
====================  ==========  =====================================

The TMF and TR-181 shapes are real: the field names, the enumerations and the
envelope structure come from published specifications, so an integration built
against them will be close. The **NXT envelope is invented**. It is the shape a
system like that plausibly emits, not the shape yours emits, and every field name
in it should be treated as a question rather than an answer.

Why adapters rather than direct parsing
---------------------------------------
Each system's message is parsed into the internal model by an adapter that
validates before it converts. A northbound feed is untrusted input: it arrives
with fields missing, enumerations the sender invented, numbers as strings, and
timestamps in whatever the sender's timezone happens to be. An adapter that
assumes well-formed input fails at the point where the data is least
recoverable.
"""

from __future__ import annotations

__all__ = ["contracts", "adapters", "samples"]
