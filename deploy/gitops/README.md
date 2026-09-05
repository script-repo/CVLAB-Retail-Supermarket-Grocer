# GitOps deployment

Full architecture and a replication checklist:
[`docs/gitops-nkp-pipeline.md`](../../docs/gitops-nkp-pipeline.md).

The deployable application is one container image, published to GHCR as
`ghcr.io/<org>/<repo>/cvlab`.

## Flow

1. A change to app inputs on `main` triggers
   `.github/workflows/publish-cvlab.yml`.
2. GitHub Actions builds `linux/amd64`, publishes `main` and immutable
   `sha-<full-commit>` tags to GHCR, and attests the image.
3. The workflow updates the environment overlay's `newTag` to the immutable
   SHA tag and commits that desired state to `main`.
4. Flux polls the repository and reconciles `deploy/gitops/<env>/` into the
   target namespace.

The `main` tag is a convenience tag. Flux deploys the immutable SHA tag written
to `kustomization.yaml`.

## Bootstrap

Flux must already be installed on the cluster. Bootstrap this repository once
by applying the matching file under `deploy/flux/`:

```bash
kubectl apply -f deploy/flux/<env>-sync.yaml
```

After bootstrap, do not apply the application overlay manually. Change Git,
allow GitHub Actions to publish the image and update its tag, then let Flux
reconcile.

Do **not** apply `cv-lab/deploy/k8s/` into a Flux-managed namespace. That
folder is the older hand-apply path.

## Workload shape

- Replica count, Service type, and NodePort (if any) are set in the overlay
- No PVC by default: YOLO weights are in the image; uploads and scratch use
  `emptyDir`
- Non-secret environment metadata comes from the overlay ConfigMap
- Optional LLM credentials are an out-of-band Secret, not committed

## Package visibility

The GHCR package must be public for an unauthenticated cluster pull. If it is
kept private, create an `imagePullSecret` out of band and reference it from
the Deployment; never commit registry credentials.
