# Devbox launch checklist

Work top to bottom. Laptop commands run from the repo root (`~/dev/devbox`).
Each command block says where it runs:

- **laptop**: your Mac terminal
- **ssm**: admin shell on the box, opened with `aws ssm start-session --target "$INSTANCE_ID"` (later: `devbox ssm`)
- **devbox**: `ssh devbox`, as the unprivileged `dev` user

Shell variables used throughout (laptop):

```bash
export AWS_REGION=us-east-1          # pick your region
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

---

## 1. Laptop prerequisites (MacOS)

- [ ] AWS CLI v2: `brew install awscli`
- [ ] Session Manager plugin: `brew install --cask session-manager-plugin`
- [ ] Tailscale app installed and signed in; **MagicDNS enabled** (admin console > DNS)
- [ ] A dedicated SSH key with a passphrase, stored in the macOS keychain:
  ```bash
  ssh-keygen -t ed25519 -f ~/.ssh/devbox_ed25519 -C devbox
  ssh-add --apple-use-keychain ~/.ssh/devbox_ed25519
  ```

## 2. AWS account hardening (one-time)

- [ ] Root user has MFA and **no access keys**. Never use root day to day.
- [ ] Day-to-day identity is an IAM Identity Center user (`aws sso login`) or an IAM user with MFA.
- [ ] EBS encryption on by default in this region (hibernation requires an encrypted root volume):
  ```bash
  aws ec2 enable-ebs-encryption-by-default
  ```
- [ ] IMDSv2 required by default for new instances:
  ```bash
  aws ec2 modify-instance-metadata-defaults --http-tokens required --http-put-response-hop-limit 1
  ```
- [ ] Cost budget with email alerts (Billing > Budgets > Monthly cost budget, e.g. $75, alert at 80% actual and 100% forecast).
- [ ] Optional: GuardDuty (`aws guardduty create-detector --enable`), 30-day trial then a few $/month at this size.
- [ ] Nothing to do for CloudTrail: 90-day event history is on by default and records every start/stop/hibernate.

## 3. Tailscale

- [ ] Tailnet policy (admin console > Access controls). Merge into your existing policy:
  ```jsonc
  {
    "tagOwners": {
      "tag:devbox": ["autogroup:admin"]
    },
    "grants": [
      // Your devices may reach anything on the devbox (SSH + dev server ports).
      { "src": ["autogroup:member"], "dst": ["tag:devbox"], "ip": ["*"] }
      // Deliberately no grant with src tag:devbox: the box can't open
      // connections to your laptop or other devices.
    ]
  }
  ```
  If the policy still contains the default allow-all rule (`"src": ["*"], "dst": ["*"]`), narrow it, or the devbox can reach your laptop.
- [ ] Generate an auth key (Settings > Keys): **Reusable off, Ephemeral off, Pre-approved on, Tags `tag:devbox`, Expiration 1 day**. Tagged nodes never hit key expiry, so the box won't drop off the tailnet after 180 days.
- [ ] Store it in Parameter Store without it touching shell history (laptop):
  ```bash
  read -rs TS_KEY && aws ssm put-parameter --name /devbox/tailscale-authkey \
    --type SecureString --value "$TS_KEY" --overwrite && unset TS_KEY
  ```

## 4. Instance IAM role

laptop:
```bash
aws iam create-role --role-name devbox-instance \
  --assume-role-policy-document file://ec2/iam/instance-trust.json
aws iam attach-role-policy --role-name devbox-instance \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam put-role-policy --role-name devbox-instance --policy-name devbox-self \
  --policy-document file://ec2/iam/instance-policy.json
aws iam create-instance-profile --instance-profile-name devbox-instance
aws iam add-role-to-instance-profile --instance-profile-name devbox-instance \
  --role-name devbox-instance
```

- [ ] Role created. It can do exactly three things: talk to SSM, hibernate instances tagged `Name=devbox`, read `/devbox/*` parameters. **Never add more**: every process on the box, including agents, can use these credentials.
- [ ] Optional: give the laptop a least-privilege profile for day-to-day `devbox` use with [`iam/laptop-policy.json`](iam/laptop-policy.json) (start/stop/describe the devbox and open SSM sessions to it), instead of admin credentials.

## 5. Security group (no inbound)

laptop:
```bash
VPC_ID=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
SG_ID=$(aws ec2 create-security-group --group-name devbox \
  --description "devbox - no inbound" --vpc-id "$VPC_ID" \
  --query GroupId --output text)
aws ec2 describe-security-groups --group-ids "$SG_ID" \
  --query 'SecurityGroups[0].IpPermissions'
```

- [ ] The last command prints `[]`. Outbound stays at the default allow-all (Tailscale, SSM, package repos, GitHub, model APIs all need it).

## 6. SSH key pair

laptop:
```bash
aws ec2 import-key-pair --key-name devbox \
  --public-key-material fileb://~/.ssh/devbox_ed25519.pub
```

- [ ] Imported. The bootstrap copies this key to `dev`; `ec2-user` SSH is disabled (`AllowUsers dev`).

## 7. Launch

laptop:
```bash
AMI_ID=$(aws ssm get-parameter \
  --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64 \
  --query Parameter.Value --output text)

INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type t4g.small \
  --key-name devbox \
  --security-group-ids "$SG_ID" \
  --iam-instance-profile Name=devbox-instance \
  --hibernation-options Configured=true \
  --metadata-options HttpEndpoint=enabled,HttpTokens=required,HttpPutResponseHopLimit=1,InstanceMetadataTags=enabled \
  --credit-specification CpuCredits=unlimited \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=40,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}' \
  --disable-api-termination \
  --user-data file://ec2/bootstrap.sh \
  --tag-specifications \
    'ResourceType=instance,Tags=[{Key=Name,Value=devbox}]' \
    'ResourceType=volume,Tags=[{Key=Name,Value=devbox}]' \
  --query 'Instances[0].InstanceId' --output text)
echo "$INSTANCE_ID"
```

| Flag | Why |
|---|---|
| `al2023-ami-kernel-default-arm64` | Standard (not minimal) AL2023: ships hibinit agent, AWS CLI, SSM agent |
| `--hibernation-options Configured=true` | **Can only be set at launch.** Without it, auto-hibernate can never work |
| `HttpTokens=required,HttpPutResponseHopLimit=1` | IMDSv2 only; containers and SSRF'd dev servers can't reach instance credentials |
| `InstanceMetadataTags=enabled` | Lets bootstrap read the Name tag from IMDS (no extra IAM). Safe: hop limit 1, and Name is not a secret |
| `VolumeSize=40`, `Encrypted=true` | Hibernation requires encryption. 40 GB = OS + projects + 4 GB hibernation image + 2 GB swapfile |
| `--disable-api-termination` | A stray `terminate-instances` can't delete the box |
| `Name=devbox` tag | The IAM policies and the laptop helper find the instance by it |

- [ ] Confirm the launch settings took:
  ```bash
  aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --query \
    'Reservations[0].Instances[0].[HibernationOptions.Configured,MetadataOptions.HttpTokens,MetadataOptions.InstanceMetadataTags,BlockDeviceMappings[0].Ebs.VolumeId]'
  ```
  Expect `True`, `required`, `enabled`, and a volume id. On an already-running instance: `aws ec2 modify-instance-metadata-options --instance-id "$INSTANCE_ID" --instance-metadata-tags enabled`.

## 8. Watch the bootstrap

The SSM agent takes a minute or two to register after boot.

ssm:
```bash
sudo cloud-init status --wait
sudo tail -n 40 /var/log/devbox-bootstrap.log
sudo journalctl -u hibinit-agent --no-pager | tail -n 20
```

- [ ] Log ends with `Bootstrap complete` and contains no `!!! WARNING` lines.
- [ ] hibinit-agent log shows the swap file created and the resume offset set, with no "Insufficient disk space".
- [ ] Reboot once, so any kernel installed by the bootstrap's upgrade is running (this also tests the reboot path): `sudo reboot`

If the bootstrap failed partway, fix the cause and re-run it (it is idempotent):
`sudo bash /var/lib/cloud/instance/scripts/part-001`

## 9. Wire up the laptop

- [ ] Delete the auth key parameter (the key is single-use, this is hygiene):
  ```bash
  aws ssm delete-parameter --name /devbox/tailscale-authkey
  ```
- [ ] Tailscale admin console shows `devbox` with `tag:devbox` and "Expiry disabled".
- [ ] Append [`laptop/ssh_config`](laptop/ssh_config) to `~/.ssh/config`.
- [ ] Put the helper on your PATH:
  ```bash
  mkdir -p ~/.local/bin && ln -sf ~/dev/devbox/ec2/laptop/devbox ~/.local/bin/devbox
  ```
- [ ] `devbox status` prints the instance id, `running`, `t4g.small`.
- [ ] `ssh devbox` lands you in `/home/dev`.

Negative checks (all must fail):

- [ ] `ssh ec2-user@devbox` is refused (`Permission denied`).
- [ ] `ssh -A devbox 'ssh-add -l'` reports no agent (forwarding refused server-side).
- [ ] The public IP is dark:
  ```bash
  PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
  nc -z -G 5 "$PUBLIC_IP" 22 && echo "EXPOSED" || echo "closed, good"
  ```
- [ ] `devbox: sudo -n true` fails (no sudo for the agent user).

## 10. Agent credentials (devbox)

Rule of thumb: **anything the agent can read can leak.** Give the box its own, narrowly scoped, revocable credentials.

- [ ] `claude`: sign in.
- [ ] Git identity: `git config --global user.name "..."` and `user.email` (your GitHub noreply address works: Settings > Emails).
- [ ] GitHub token: on github.com, Settings > Developer settings > Fine-grained tokens > Generate:
  - **Name** `devbox`, **Expiration** 90 days or less
  - **Repository access**: only select repositories (the ones the box works on)
  - **Permissions**: Contents read/write, Pull requests read/write (Metadata read-only is added automatically). Add Issues read/write only if agents should touch issues.
- [ ] Sign `gh` in with it, without the token touching shell history (devbox):
  ```bash
  read -rs GH_PAT && printf '%s' "$GH_PAT" | gh auth login --with-token && unset GH_PAT
  gh auth setup-git                  # git uses gh for github.com HTTPS credentials
  gh config set git_protocol https   # clone over HTTPS so the token applies
  ```
- [ ] `gh auth status` shows you logged in to github.com. Then check a repo end to end: `gh repo clone <owner>/<repo>`, commit on a branch, `git push`, `gh pr create --draft`, then close the test PR.
- [ ] Put an expiry reminder in your calendar. When the token expires, generate a new one and re-run the `gh auth login --with-token` line.
- [ ] Note: with no keyring on the box, `gh` stores the token in plain text in `~/.config/gh/hosts.yml`. Agents can read it, which is why its scope stays narrow.
- [ ] Never put on the box: AWS access keys, production secrets, your main GitHub SSH key. Never `ssh -A` into it.

## 11. Verify

Shorten the idle window while testing (ssm):
```bash
sudo sed -i 's/^IDLE_MINUTES=.*/IDLE_MINUTES=10/' /etc/devbox/idle.conf
sudo journalctl -t devbox-idle -f        # leave this running in an SSM tab
```

Each check below says what `journalctl -t devbox-idle` should show.

**Baseline** (ssm)
- [ ] `swapon --show`: `zram0` priority 100 and `/swapfile` priority 10. `/swap` is **not** listed (hibinit only enables it while hibernating).
- [ ] `sudo nft list table inet devbox` prints the ruleset.
- [ ] `systemctl list-timers 'devbox-*'` lists `devbox-idle.timer` and `devbox-update.timer`.

**Hibernate and resume** (devbox, then laptop)
- [ ] In `tmux new -s main`: start a dev server in a sample project with `npm run dev -- --host`, open `http://devbox:5173` on the laptop.
- [ ] In a second tmux window, start `claude` on a small task. Note `uptime -s`.
- [ ] Detach, then `devbox down`. `devbox status` goes `stopping` then `stopped`, and
  ```bash
  aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].StateReason.Message'
  ```
  mentions hibernation.
- [ ] `ssh devbox` wakes it. `uptime -s` is **unchanged** (resume, not reboot); `tmux attach` shows the agent and dev server alive; the browser page reloads without restarting the server.
- [ ] Journal after resume: `idle check 1/2`, not an immediate hibernate.

**Stays awake**
- [ ] Agent working on a long task, SSH closed, **laptop lid closed**: journal shows `active (agent heartbeat)` throughout.
- [ ] SSH session open and idle: `active (ssh session)`.
- [ ] CPU-bound work with no agent and no SSH (devbox, in tmux, then detach and log out):
  ```bash
  timeout 20m sh -c 'yes >/dev/null & yes >/dev/null & wait'
  ```
  Journal: `active (load ... > 0.5)`.

**Hibernates**
- [ ] Agent waiting on a question for you, SSH closed: hibernates after the window; after wake it is still waiting on the same question.
- [ ] Close the lid with an SSH session open: the session is dropped within about 3 minutes, then the box hibernates after the window.
- [ ] A browser tab left open on the dev server does **not** keep it awake.

**Mid-task**
- [ ] `devbox down` while the agent is working: after `ssh devbox` the agent carries on (in-flight API call retried).

**Reboot**
- [ ] ssm: `sudo reboot`. Afterwards Tailscale reconnects, `ssh devbox` works, both timers are active, and a `devbox down` / `ssh devbox` cycle still resumes correctly.

**Cost** (after a few days)
- [ ] Cost Explorer (EC2 running hours) matches actual use; CloudTrail `StopInstances` events line up with the idle journal.

Restore the real window (ssm):
```bash
sudo sed -i 's/^IDLE_MINUTES=.*/IDLE_MINUTES=30/' /etc/devbox/idle.conf
```

## 12. Upgrading the instance type (after verification)

1. `devbox stop` (a **full stop**: a hibernated instance can't change type). Wait for `stopped`.
2. Make room on the root volume for the new RAM size. Rule: root >= used space + RAM (hibernation image) + runtime swap + headroom. For 16 GB RAM:
   ```bash
   VOL_ID=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
     --query 'Reservations[0].Instances[0].BlockDeviceMappings[0].Ebs.VolumeId' --output text)
   aws ec2 modify-volume --volume-id "$VOL_ID" --size 100
   ```
   cloud-init grows the partition and filesystem on the next boot.
3. `aws ec2 modify-instance-attribute --instance-id "$INSTANCE_ID" --instance-type '{"Value": "t4g.xlarge"}'`
4. `devbox up`. ssm: `df -h /`, then `sudo journalctl -u hibinit-agent -b` shows `/swap` recreated at the new RAM size. If it complained about disk space (it may run before the filesystem grows), `sudo systemctl restart hibinit-agent`.
5. Raise `RUNTIME_SWAP_MB` in `bootstrap.sh` (e.g. `8192`), copy it over and re-run it:
   ```bash
   scp ec2/bootstrap.sh devbox:            # laptop
   sudo bash /home/dev/bootstrap.sh        # ssm
   ```
6. Re-run the **Hibernate and resume** checks in section 11. The idle load threshold scales with core count automatically.

## 13. Backups (optional)

- [ ] EC2 > Lifecycle Manager > Create EBS snapshot policy targeting tag `Name=devbox`, daily, keep 7. Snapshots are incremental, so this is cheap.

## 14. Troubleshooting

| Symptom | Look at |
|---|---|
| `ssh devbox` hangs | `devbox status`; `devbox ssm` then `sudo tailscale status`, `systemctl status sshd`, `sudo nft list ruleset` |
| Never hibernates | `journalctl -t devbox-idle` names what keeps it active |
| Tries to hibernate, fails | `journalctl -u devbox-idle.service`: `UnauthorizedOperation` means the role policy or `Name` tag is wrong; `UnsupportedHibernationConfiguration` means the instance was launched without hibernation (relaunch) |
| Resume came back as a fresh boot | `sudo journalctl -u hibinit-agent -b -1`; if zram is implicated, remove the zram section from `bootstrap.sh`, delete `/etc/systemd/zram-generator.conf`, reboot, re-test |
| Need it to stay up regardless | set `IDLE_HIBERNATE=off` in `/etc/devbox/idle.conf` |
| Locked out of SSH entirely | `devbox ssm` always works: it needs no inbound port or Tailscale |

## 15. Teardown

laptop:
```bash
aws ec2 modify-instance-attribute --instance-id "$INSTANCE_ID" --no-disable-api-termination
aws ec2 terminate-instances --instance-ids "$INSTANCE_ID"
aws ec2 wait instance-terminated --instance-ids "$INSTANCE_ID"
aws ec2 delete-security-group --group-id "$SG_ID"
aws ec2 delete-key-pair --key-name devbox
aws iam remove-role-from-instance-profile --instance-profile-name devbox-instance --role-name devbox-instance
aws iam delete-instance-profile --instance-profile-name devbox-instance
aws iam delete-role-policy --role-name devbox-instance --policy-name devbox-self
aws iam detach-role-policy --role-name devbox-instance \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam delete-role --role-name devbox-instance
```
- [ ] Remove the `devbox` machine in the Tailscale admin console.
- [ ] Revoke the box's GitHub fine-grained token (github.com > Settings > Developer settings) and its Claude session.
