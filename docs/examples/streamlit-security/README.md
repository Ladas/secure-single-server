# Streamlit before and after OpenShell

Run the same Streamlit support-copilot twice. First it runs in an ordinary
container with the real model key in the application process. Then it runs in
OpenShell with an attached provider, a read-only application directory, and a
hard-required Landlock policy. The provider profile authorizes the credential
only for `POST /v1/chat/completions`.

```text
ordinary container
  → real model key inside the app
  → app can write to its own directory
  → app can read a synthetic marker outside its application directory

OpenShell sandbox
  → app receives an opaque credential placeholder
  → OpenShell substitutes the real key at the authorized endpoint
  → app directory is read-only
  → synthetic marker outside the allowed paths is unreadable
```

## Before you start

### Where to run it

AWS is not required. Use any qualified OpenShell deployment on a RHEL 9 x86_64
Linux host, including a local or cloud VM. Run the commands from the deployed
repository checkout: `/usr/share/secure-single-server` on a bootc image or
`/opt/secure-single-server` after a manual deployment.

The unsafe half only needs Podman. The OpenShell half requires the OpenShell
gateway, rootless Podman, and Landlock ABI 3 or newer, so it is intended for a
VM, bare-metal host, or bootc host rather than an ordinary nested container. If
the demo host is remote, open the matching SSH tunnel before starting each
version, then open Streamlit in your local browser. The unsafe container uses
local port `8501`; the OpenShell service uses local port `8090`.

For the unsafe version, keep this tunnel open:

```console
ssh -N -L 8501:127.0.0.1:8501 user@open-shell-host
```

Use a dedicated model API key and endpoint for the demo. The ordinary run
exposes the key to app code, so use HTTPS. In OpenShell, the app receives an
opaque placeholder and the provider supplies the key only for an authorized
request.

### OpenAI

Import the demo provider profile:

```console
openshell profile lint -f openshell/demos/streamlit-security/providers/openai.yaml
openshell profile import -f openshell/demos/streamlit-security/providers/openai.yaml
```

Create the provider and enter the real key at the hidden prompt:

```console
read -r -s -p "OpenAI API key: " OPENAI_API_KEY; printf '\n'
export OPENAI_API_KEY
openshell provider create \
  --name streamlit-demo-openai \
  --type streamlit-openai \
  --credential OPENAI_API_KEY
unset OPENAI_API_KEY
```

### OpenAI-compatible endpoint

Edit the host and port in
`openshell/demos/streamlit-security/providers/openai-compatible.yaml`, then:

```console
openshell profile lint -f openshell/demos/streamlit-security/providers/openai-compatible.yaml
openshell profile import -f openshell/demos/streamlit-security/providers/openai-compatible.yaml

read -r -s -p "Compatible endpoint key: " OPENAI_API_KEY; printf '\n'
export OPENAI_API_KEY
openshell provider create \
  --name streamlit-demo-compatible \
  --type streamlit-openai-compatible \
  --credential OPENAI_API_KEY
unset OPENAI_API_KEY

export MODEL_BASE_URL=https://your-endpoint/v1
export OPENAI_MODEL=your-model-id
```

## Run the unsafe version

From the repository root:

```console
read -r -s -p "OpenAI API key: " OPENAI_API_KEY; printf '\n'
export OPENAI_API_KEY
export MODEL_BASE_URL=https://api.openai.com/v1
export OPENAI_MODEL=gpt-5.5

openshell/demos/streamlit-security/run-unsafe.sh
unset OPENAI_API_KEY
```

Open `http://localhost:8501`. Choose **Summarize with model**, then choose both
diagnostics. The model call succeeds, the app writes a fake marker to
`/opt/openshell-demo/leaked-marker`, and it reads the synthetic marker at
`/opt/openshell-demo-secret`.

Both versions include the same follow-up chat. It sends questions to the model;
the diagnostics remain the only local actions.

## Run the OpenShell version

Select the provider, native endpoint, and model:

```console
export STREAMLIT_DEMO_PROVIDER=streamlit-demo-openai
export MODEL_BASE_URL=https://api.openai.com/v1
export OPENAI_MODEL=gpt-5.5
```

Then start the sandbox:

```console
openshell/demos/streamlit-security/run-safe.sh
```

Open the URL printed by `run-safe.sh`. The same model summary works, but both
diagnostics are denied: `/opt/openshell-demo` is read-only and
`/opt/openshell-demo-secret` is outside the policy's allowed read paths.

OpenShell's gateway routes exposed services by hostname. Use the exact URL
printed by `run-safe.sh`; `http://localhost:8090` reaches the gateway's default
route and returns `404`, not the Streamlit app.

If OpenShell runs on a remote host, keep an SSH tunnel open before starting
the demo:

```console
ssh -N -L 8090:127.0.0.1:8090 user@open-shell-host
```

Replace `user@open-shell-host` with your SSH username and OpenShell host.

Optionally verify the boundary:

```console
openshell/demos/streamlit-security/verify.sh
```

## Cleanup

Stop the unsafe container with `Ctrl-C`. Remove the OpenShell sandbox and its
exposed service with:

```console
openshell service delete streamlit-demo streamlit
openshell sandbox delete streamlit-demo
```

## What this proves

- The unsafe app holds the real model key and can modify its own application
  directory and read the synthetic marker outside it.
- The OpenShell app holds only an opaque placeholder; OpenShell substitutes the
  real key at the endpoint authorized by the provider profile.
- OpenShell makes the application directory read-only, makes the synthetic
  marker unreadable, and requires Landlock.
- The demo uses synthetic markers, never real credentials or real host files.

## What this does not prove

This focused demo shows credential substitution and two filesystem boundaries
for one application; it does not test every syscall, network route, container
escape, or supply-chain boundary. Keep the read target synthetic; do not point
the diagnostic at real host files.
