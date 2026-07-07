# Limitation-targeted benchmark extension for deterministic methods

## Abstract
_Abstract stub:_ This draft frames the selected candidate as a manuscript-ready direction. It targets the gap 'The evidence cards consistently indicate deterministic methods with benchmark evaluations and reported experiment signals, but the cited limitations are only described as future-work-addressable and are not specified in the supplied metadata. This creates a gap between benchmark performance and actionable understanding of where deterministic approaches fail.' and remains grounded in the cited evidence anchors while preserving explicit critic and risk notes for later revision.

## Introduction
### Gap
The evidence cards consistently indicate deterministic methods with benchmark evaluations and reported experiment signals, but the cited limitations are only described as future-work-addressable and are not specified in the supplied metadata. This creates a gap between benchmark performance and actionable understanding of where deterministic approaches fail.

### Evidence Anchors
- Evidence anchor (arXiv 2401.14196 / 2401.14196): A highlighted limitation is identified as something future work can address.
- Evidence anchor (arXiv 2505.18705 / 2505.18705): future work direction
- Evidence anchor (arXiv 2312.13010 / 2312.13010): A future work direction is mentioned.
- Evidence anchor (arXiv 2312.10997 / 2312.10997): The abstract mentions a "future work direction".
- Evidence anchor (arXiv 2502.05957 / 2502.05957): The abstract mentions a "future work direction".

## Related and Future-Work Motivation
The selected papers motivate this direction by combining reported limitations, future-work clues, and transferable evaluation signals that justify a concrete follow-on manuscript draft.
- arXiv 2401.14196 (2401.14196) motivates follow-on work via: A highlighted limitation is identified as something future work can address.
- arXiv 2505.18705 (2505.18705) motivates follow-on work via: future work direction
- arXiv 2312.13010 (2312.13010) motivates follow-on work via: A future work direction is mentioned.
- arXiv 2312.10997 (2312.10997) motivates follow-on work via: The abstract mentions a "future work direction".
- arXiv 2502.05957 (2502.05957) motivates follow-on work via: The abstract mentions a "future work direction".

## Proposed Direction
### Hypothesis
If benchmark suites are extended with explicit limitation-targeted stress tests and failure-mode labels, then future deterministic methods can be evaluated more transparently against the kinds of weaknesses that current papers identify only at a high level.

### Method
Create a benchmark-extension protocol for deterministic methods: collect the limitation statements from the referenced works, convert each into a measurable stress condition when possible, define failure-mode labels, and run the original deterministic method alongside controlled variants. Where the supplied papers do not specify the limitation, the protocol would require authors to operationalize it before inclusion rather than infer it externally.

### Contribution
A practical framework for turning vague future-work limitations into concrete benchmark dimensions, helping future studies report not only aggregate performance but also limitation-specific behavior.

## Evaluation Plan
### Evaluation
Evaluate the protocol by applying it to the deterministic methods associated with the referenced benchmark evaluations. Compare standard benchmark scores with limitation-targeted scores, report whether the added tests expose different experiment signals, and measure reproducibility across repeated deterministic runs.
- Evaluation anchor (arXiv 2401.14196 / 2401.14196): Benchmark evaluation
- Evaluation anchor (arXiv 2505.18705 / 2505.18705): benchmark evaluation
- Evaluation anchor (arXiv 2312.13010 / 2312.13010): Benchmark evaluation is mentioned.
- Evaluation anchor (arXiv 2312.10997 / 2312.10997): The abstract states that the work includes a "benchmark evaluation".
- Evaluation anchor (arXiv 2502.05957 / 2502.05957): The abstract mentions a "benchmark evaluation".

## Limitations and Risks
### Risk Notes
- Critic verdict: pass
- Novelty risk: unknown
- Candidate risk: The supplied metadata does not specify the actual limitations, so the first phase may depend on access to full papers or author-provided clarifications.
- Candidate risk: Stress tests may be too paper-specific to generalize across all deterministic methods.
- Candidate risk: Additional benchmark dimensions may increase evaluation cost without changing conclusions for some methods.
- Critic weakness: External novelty verification intentionally deferred by selected_only policy.
- Required fix: Run light_external or strong_external verification before selection if novelty must be verified.

## Conclusion
In summary, A practical framework for turning vague future-work limitations into concrete benchmark dimensions, helping future studies report not only aggregate performance but also limitation-specific behavior. The manuscript should advance only after the documented risk notes and required fixes are addressed.

## Claim Map and Traceability Notes
- Candidate ID: cand-r1-1
- Selected candidate path: selected_candidate.json
- gap -> candidate.gap_statement -> refs: 2401.14196, 2505.18705, 2312.13010, 2312.10997, 2502.05957
- hypothesis -> candidate.hypothesis -> refs: 2401.14196, 2505.18705, 2312.13010, 2312.10997, 2502.05957
- method -> candidate.proposed_method -> refs: 2401.14196, 2505.18705, 2312.13010, 2312.10997, 2502.05957
- evaluation -> candidate.evaluation_plan -> refs: 2401.14196, 2505.18705, 2312.13010, 2312.10997, 2502.05957
- contribution -> candidate.expected_contribution -> refs: 2401.14196, 2505.18705, 2312.13010, 2312.10997, 2502.05957

## Revision Update
Request addressed: 평가 계획과 한계 부분을 더 명확히 보강해줘.
Selected candidate: cand-r1-1
Evidence anchors: 2401.14196, 2505.18705, 2312.13010, 2312.10997, 2502.05957
Critic weakness: External novelty verification intentionally deferred by selected_only policy.
Required fix: Run light_external or strong_external verification before selection if novelty must be verified.
