# GitOps deployment

Full architecture and a replication checklist:
[`docs/gitops-nkp-pipeline.md`](../../docs/gitops-nkp-pipeline.md).

The deployable application is one container image:

```text
ghcr.io/script-repo/cvlab-retail-supermarket-grocer/cvlab
```

## Flow

1. A change to app inputs on `main` triggers
   `.github/workflows/publish-cvlab.yml`.
2. GitHub Actions builds `linux/amd64`, publishes `main` and immutable
   `sha-<full-commit>` tags to GHCR, and attests the image.
3. The workflow updates this environment's `newTag` to the immutable SHA tag
   and commits that desired state to `main`.
4. Flux polls the public repository and reconciles
   `deploy/gitops/db-project-002/` into the `db-project-002` namespace.

The `main` tag is a convenience tag. Flux deploys the immutable SHA tag written
to `kustomization.yaml`.

## Bootstrap

Flux is already installed on NKP. Bootstrap this repository once:

```bash
kubectl apply -f deploy/flux/db-project-002-sync.yaml
```

After bootstrap, do not apply the application overlay manually. Change Git,
allow GitHub Actions to publish the image and update its tag, then let Flux
reconcile.

Do **not** apply `cv-lab/deploy/k8s/` into `db-project-002`. That folder is the
older hand-apply path.

## Live lab

- One replica
- NodePort `30008`
- No PVC: YOLO weights are in the image; uploads and scratch use `emptyDir`
- Non-secret environment metadata comes from `cvlab-config`
- Optional LLM credentials are an out-of-band `nai-credentials` Secret

The NodePort is reachable at port `30008` on any NKP node IP
(`http://10.42.156.95:30008`).

## Package visibility

The GHCR package must be public for an unauthenticated NKP pull. If it is kept
private, create an `imagePullSecret` out of band and reference it from the
Deployment; never commit registry credentials.
