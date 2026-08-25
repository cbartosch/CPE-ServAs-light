# Executive demo experience — Hotfix5.5

Hotfix5.5 changes the presentation layer, not the operating-control semantics.
The unified Streamlit application is organized around a C-level narrative:

1. **Prevent** — show predicted service risk before or at the point of degradation.
2. **Connect** — show Customer Care attaching to predictive evidence and one root incident.
3. **Control** — show deterministic controls, AI reconciliation and explicit human gates.
4. **Prove** — keep raw evidence and audit records available through progressive disclosure.

## Executive landing view

The Digital Twin page now opens on an executive scorecard instead of a generator
form. It summarizes homes modeled, predicted risks, Customer Care contacts with
pre-existing predictive evidence, duplicate incidents suppressed, closure state
and the human-review workload. All values are computed from the selected synthetic
run; no financial or operational KPI is invented in the presentation layer.

## Navigation and language

The main sidebar uses three groups: Executive, Operations and Governance. Technical
labels are retained only where they help an operator or are placed under expanders.
The Digital Twin page uses business-facing tabs: Executive View, Create Demo,
Predictive Health, Customer Experience, Subscriber Story, Decisions & Controls,
and Evidence & Audit.

## Visual system

Hotfix5.5 adds an executive presentation layer with a navy/teal command-center
palette, restrained gradients, elevated KPI cards, clearer section hierarchy,
compact status pills, simplified tables and progressive disclosure of raw JSON.
The existing simulation and production-write disclosures remain visible.

## Demo talk track

Start at **Executive View**, move to **Predictive Health** for the leading signal,
then open **Customer Experience** to show the same service attached to the same
root incident. Finish in **Decisions & Controls** or **Evidence & Audit** to show
that AI does not replace the operating standard: it is reconciled to deterministic
controls and closure still requires objective restoration evidence.
