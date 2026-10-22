# Third-party provenance

This is a research integration overlay, not a replacement distribution of vLLM or MindIE Motor.

- Motor source excerpts and patches derive from Ascend/MindIE-Motor f203263d9742dd6fa76eaef658e0ff3a0f380301. Original copyright and Mulan PSL v2 headers are retained; license text is included under licenses/ in the release.
- vLLM and vLLM-Ascend reference source files retain their original license notices. License texts are copied into licenses/ in the release.
- evidence/source_drops contains unchanged user-supplied experimental proxy/slo_patch material retained locally for internal reproduction; it is excluded from the root Git repository. tests/fixtures/g4_fgjsq_reference.py contains only two unchanged algorithm classes used as the test oracle, with source hashes and line provenance beside it. No additional third-party redistribution rights are asserted.
- No model weights, predictor model, container image, NPU binary, or native Motor SHM library is included.

Pinned upstream license texts are retained in licenses/. No new project-wide open-source license is selected by this version cleanup.
