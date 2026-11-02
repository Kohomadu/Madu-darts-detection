# Autodarts-shaped local event stream

Madu’s detection process publishes its own state over local HTTP/WS using the Autodarts 2.1 shape (`status`/`event`, full `throws[]` with flat `coordsX/Y`, `segmentName`, `bed`, `multiplier`, `method`). A thinner Madu-only Hit event format would be simpler, but mirroring the Autodarts shape lets every visit be diffed field-for-field against the live Board during development and keeps a future match UI portable between the two; the data is still produced entirely by Madu, never read from Autodarts in the product path (ADR 0001).
