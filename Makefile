# `aws login` / SSO sessions are not readable by Terraform directly, so export them first.
CREDS := eval "$$(aws configure export-credentials --format env 2>/dev/null)";
TF   := $(CREDS) terraform -chdir=infra
PY   := .venv/bin/python

.PHONY: help setup test layer bootstrap init plan deploy url code logs tail-api images batch destroy

help:
	@echo "setup      create .venv with dev dependencies"
	@echo "test       run unit tests"
	@echo "bootstrap  (once per account) create shared Terraform state bucket"
	@echo "init       terraform init against the shared state"
	@echo "deploy     build Pillow layer + terraform apply"
	@echo "url/code   print the live URL / team code"
	@echo "logs       tail processor logs in the terminal"
	@echo "images     generate synthetic test images in test_images/"
	@echo "batch      run test_images/ through the live API -> results/metrics.csv"
	@echo "destroy    tear everything down (scripts/teardown.sh)"

setup:
	uv venv -q .venv && uv pip install -q --python $(PY) -r requirements-dev.txt

test:
	$(PY) -m pytest -q tests

layer:
	./scripts/build_layer.sh

bootstrap:
	./scripts/bootstrap_state.sh

init:
	$(TF) init -backend-config=backend.hcl

plan: layer
	$(TF) plan

deploy: test layer
	$(TF) apply
	@echo; echo "Live URL:  $$($(TF) output -raw web_url)"; echo "Team code: $$($(TF) output -raw team_code)"

url:
	@$(TF) output -raw web_url; echo

code:
	@$(TF) output -raw team_code; echo

logs:
	aws logs tail "$$($(TF) output -raw processor_log_group)" --follow --format short --region eu-west-1

tail-api:
	aws logs tail "$$($(TF) output -raw api_log_group)" --follow --format short --region eu-west-1

images:
	$(PY) scripts/gen_test_images.py

batch:
	$(PY) scripts/batch_test.py --url "$$($(TF) output -raw web_url)" --code "$$($(TF) output -raw team_code)"

destroy:
	./scripts/teardown.sh
