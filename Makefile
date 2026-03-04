.PHONY: test eval eval-sample validate-eval-corpus

EVAL_CORPUS ?= examples/eval_corpus_v1.json
EVAL_OUTPUT ?= artifacts/eval-report.json
EVAL_EXTRA_ARGS ?=

test:
	uv run pytest -q

eval:
	mkdir -p "$(dir $(EVAL_OUTPUT))"
	uv run banana-split --eval-corpus "$(EVAL_CORPUS)" --eval-output "$(EVAL_OUTPUT)" $(EVAL_EXTRA_ARGS)

eval-sample:
	$(MAKE) eval EVAL_CORPUS=examples/eval_corpus.sample.json

validate-eval-corpus:
	uv run python scripts/validate_eval_corpus.py "$(EVAL_CORPUS)"
