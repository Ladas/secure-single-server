# Manual OpenShell testing on all-in-one

Reuse all-in-one after direct harness tests. Keep real Qwen installed and use
the ordinary login from [user setup](../quickstarts/all-in-one/accounts.md). OpenCode is the first
Praxis integration to qualify here. Bootc has separate CPU/GPU evidence; this
mutable RHEL path still requires a live sandbox run. See the
[execution matrix](compatibility.md#all-in-one).

This is a trusted test host: the current OpenShell management API trusts local
users. Registering an ordinary client gives it sandbox management access, not
a private per-user control plane. Keep ports 8090/8091 on loopback. See the
[deployment boundary](../../openshell/docs/threat-model.md).

## 1. Administrator: install the addon

From the administrator SSH session on all-in-one:

```console
cd ~/secure-single-server-deploy
sudo scripts/openshell-praxis/install --owner openshell-svc
```

If already installed by the mock suite, this recovers the same managed addon.
Praxis, its provider secrets and vLLM remain in their existing service account.
Publish only the public recipes for the ordinary user; never copy `material/`
or the complete private deployment bundle:

```console
sudo install -d -m 0755 /opt/praxis-test-recipes/scripts/common /opt/praxis-test-recipes/configs \
  /opt/praxis-test-recipes/openshell/scripts
sudo cp -R openshell/configs openshell/harnesses /opt/praxis-test-recipes/openshell/
sudo install -m 0644 openshell/scripts/lib.sh openshell/scripts/harness-lib.sh \
  /opt/praxis-test-recipes/openshell/scripts/
sudo cp -R configs/openshell-praxis /opt/praxis-test-recipes/configs/
sudo install -m 0644 scripts/common/lib.sh /opt/praxis-test-recipes/scripts/common/lib.sh
sudo chmod -R a+rX /opt/praxis-test-recipes
sudo restorecon -RF /opt/praxis-test-recipes
```

## 2. User: register the local gateway

Log in as `praxis-user`. Run without sudo, once for this account:

```console
openshell gateway add http://127.0.0.1:8090 --name local
openshell gateway select local
openshell sandbox list
```

This stores the public loopback endpoint in your own home. Do not copy service
account configuration, signing keys or provider bindings into your account.

## 3. User: start OpenCode with Qwen through Praxis

Each sandbox defaults to 2 CPUs and 4 GiB of memory. These limits apply to the
sandbox, not vLLM or aggregate host usage. To choose different limits before
creation, optionally export:

```console
export OPENSHELL_SANDBOX_CPU=2 OPENSHELL_SANDBOX_MEMORY=4Gi
```

```console
cd /opt/praxis-test-recipes
export PRAXIS_PORT=8080 PRAXIS_API_PREFIX=/vllm OPENSHELL_MODEL_ID=qwen3-8b
SANDBOX_NAME="${USER}-opencode-qwen"
openshell/harnesses/opencode/create.sh --profile dev --name "$SANDBOX_NAME" \
  --config configs/openshell-praxis
openshell/harnesses/opencode/connect.sh --name "$SANDBOX_NAME"
```

Use the [file/test task](harnesses.md#acceptance-task).
Check the generated files and rerun unittest **inside the sandbox**; host files
are not automatically mounted. Both model traffic and tool continuation must
go through Praxis. Do not attach an OpenShell direct-provider binding.

For an OpenAI experiment, first have the administrator
[enable it in Praxis](rhel-real.md#3-add-openai-to-existing-praxis), then create
a separate sandbox with these selections:

```console
printf 'OpenAI model ID: '
IFS= read -r OPENSHELL_MODEL_ID
export OPENSHELL_MODEL_ID
export PRAXIS_API_PREFIX=''
SANDBOX_NAME="${USER}-opencode-openai"
openshell/harnesses/opencode/create.sh --profile dev --name "$SANDBOX_NAME" \
  --config configs/openshell-praxis
openshell/harnesses/opencode/connect.sh --name "$SANDBOX_NAME"
```

This recipe uses Chat Completions. Anthropic, Codex and OpenClaw need separate
Praxis sandbox adapters; Claude also needs a pinned sandbox image/recipe.
Use their supported [direct client paths](harnesses.md) where available.

## 4. User: inspect or delete a test sandbox

After leaving OpenCode, independently inspect and run its tests in the sandbox:

```console
ssh -F /dev/null -o "ProxyCommand=openshell ssh-proxy --gateway-name local --name $SANDBOX_NAME" \
  "sandbox@$SANDBOX_NAME" 'pwd; ls -l add.py test_add.py; python3 -m unittest -v'
```

Run from the same sandbox project directory if you selected a different one.
Keep the sandbox for further testing, or export needed files before deletion:

```console
openshell sandbox delete "$SANDBOX_NAME"
```

A Ready sandbox or successful config upload is not harness acceptance. Record
streamed inference, an actual tool event and independently checked results;
also run the controlled network policy test before claiming confinement.
Record effective sandbox resource limits and network denials in the
[matrix](compatibility.md). Kernel/dev-server qualification is tracked in the
[debugging plan](vllm-debugging.md#5-add-sandbox-execution-without-losing-the-native-baseline).
