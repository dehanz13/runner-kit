# RunsOn: optional AWS execution provider

Evaluated 2026-10-01. Status: research only; no installed adapter, license purchase or provisioned resources.

RunsOn creates disposable EC2 runners in the operator's AWS account. Jobs can opt in individually, leaving other jobs on GitHub-hosted runners. Linux and Windows are supported; it does not manage local macOS/UTM guests. This makes it a possible additional execution provider when cloud capacity is justified. [Product overview](https://runs-on.com/)

## Integration modes

| Mode | Configuration ownership | Demand path | Implication |
|---|---|---|---|
| Flex | Workflow labels select runner resources | Public GitHub webhook ingress | More job-level flexibility; protect both provisioning permissions and ingress |
| Fleet | Terraform defines approved named fleets | Outbound scale-set demand; no inbound webhook | Better centralized policy; organization or enterprise runner-group boundary |

Fleet's documented boundary is an organization or enterprise, not a personal-account repository pool. Neither mode is a home-VM supervisor. Flex's managed private network includes a NAT Gateway; price that before selecting it. [Mode documentation](https://runs-on.com/docs/flex-vs-fleet/)

## License and cost

Commercial licensing currently starts at €300/year plus AWS usage. The noncommercial offer is free with a public acknowledgment, subject to eligibility. A private repository or personal account does not establish eligibility. Source access and redistribution rights must be checked separately before including vendor code in a public toolkit. [Pricing and terms entry point](https://runs-on.com/pricing/)

For an adoption decision, compare avoided **billed** hosted usage against license amortization, control-plane services, compute, storage, transfer, retained caches/logs, retries and maintenance. Included GitHub minutes are not cash savings unless displaced usage changes the actual bill. A faster job can still cost more overall at low volume. Vendor speed and savings claims are hypotheses until measured on representative jobs.

## Security review inputs

RunsOn documents ephemeral job instances, customer-account infrastructure, vendor license checks and launch telemetry. It also documents unencrypted runner EBS volumes by default; its stack supports `EncryptEbs=true`. Flex offers disabling setup routes and enabling WAF. Review the exact deployed version, IAM policies, AMIs and data flows. Ordinary GitHub logs/artifacts and job network traffic still need their own controls. [Security model](https://runs-on.com/docs/control-plane/security/)

Our proposed pilot would use a dedicated CI account, encrypted disks, approved repositories, minimal job permissions, short-lived deployment identities where needed, separate trusted/untrusted caches and no access to home-network services. Keep public contribution jobs on GitHub-hosted infrastructure. Avoid production deployments and other non-idempotent jobs during a Spot pilot. These are proposed adoption conditions, not verified capabilities of an installed system.

## Operating constraints

RunsOn exposes per-job operational cost estimates and termination safeguards. Its documented daily budget default is $10; notifications are delayed billing controls, not immediate spending stops. Missing pricing can produce absent estimates rather than zero cost. Reconcile estimates with billed AWS spend. [Cost controls](https://runs-on.com/docs/costs/cost-control/)

Before provisioning, define a small allowlisted machine catalog, maximum parallel jobs, maximum runtime, cache/log retention and a tested disable/cleanup procedure. Do not rely on a budget alert as a hard cap. Keep warm pools disabled in an initial low-volume experiment. Treat interrupted attempts as separate billable/benchmark observations.

## Toolkit boundary

Keep job purpose, hardware/resource requirements and reporting independent of the execution provider. Add a RunsOn mapping only after measured savings justify it. The local configuration file can be authoritative for a future reviewed nonsecret export, but it cannot be read by GitHub before runner selection. Cloud control-plane credentials need a protected cloud runtime store; never copy the central file into a runner.

No automatic failover from a home runner is implemented or implied. A queued self-hosted job does not switch provider by itself. Any future routing mechanism must avoid duplicate dispatch, chargeable retry loops and differences in secrets or trust between backends.
