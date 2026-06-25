# agent-auto-system-stack (CDK)

AWS CDK (TypeScript) infrastructure for deploying **Agent Auto System** to ECS
Fargate. Implements the phase-1 design in
[`../doc/aws-ecs-fargate-deployment.md`](../doc/aws-ecs-fargate-deployment.md):

> One always-on Fargate task behind an ALB. No NAT Gateway, no EFS, no Secrets
> Manager. Generated data (SQLite / uploads / reports) lives on the task's
> ephemeral disk and is wiped on redeploy — an accepted phase-1 trade.

The whole stack is in [`lib/agent-auto-system-stack-stack.ts`](lib/agent-auto-system-stack-stack.ts).
It builds the image from the repo's `runtime` Dockerfile stage (forced to
`linux/amd64`) and pushes it to ECR automatically on deploy.

## Deploy

API keys are read from your shell at deploy time and passed straight to the task
definition — **never hardcode them and never commit real values**.

```bash
npm install
npm run build && npm test          # tsc + jest

# First time in a new account/region:
npx cdk bootstrap

# Deploy. Export only the keys you actually use; the rest default to "".
OPENAI_API_KEY=sk-...        \
ANTHROPIC_API_KEY=sk-ant-... \
GEMINI_API_KEY=...           \
GMAIL_ADDRESS=...            \
GMAIL_APP_PASSWORD=...       \
  npx cdk deploy
```

The stack outputs the ALB DNS name; open `http://<that-name>/` to reach the app.

> **Redeploys cause ~30–60s downtime and wipe all generated data** — both are
> intentional (single SQLite writer + ephemeral disk). See the design doc §7–§8
> for the additive upgrade path (EFS / SSM / Postgres / S3).

## Useful commands

| Command | Description |
|---|---|
| `npm run build` | compile TypeScript |
| `npm test` | jest assertions against the synthesized template |
| `npx cdk synth` | emit the CloudFormation template |
| `npx cdk diff` | diff deployed stack vs. current code |
| `npx cdk deploy` | build image, push to ECR, deploy |
| `npx cdk destroy` | tear everything down |
