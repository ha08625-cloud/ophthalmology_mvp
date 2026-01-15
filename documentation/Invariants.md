Invariants list

##Project level invariants##

1. Probabilistic modules produce suggestions or signals; only deterministic modules make clinical decisions
2. Dialogue Manager coordinates flow but does not interpret, infer, or repair clinical meaning
3. State Manager stores and exports state only; it performs no clinical inference, semantic validation, or corrective logic beyond structural integrity checks
4. Episode identity is explicit and authoritative; no module infers or reconstructs episodes implicitly
5. Dialogue Manager is the only module that composes other modules
6. Clinical rules and thresholds are data-defined; modules do not encode medical policy
7. Replay extraction occurs only via dedicated, validated replay input object.
8. Clinical vs operational data boundary
