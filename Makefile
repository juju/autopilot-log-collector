.PHONY: test
test:
	python -m unittest test_collect-logs


.PHONY: ci-test
ci-test: test
