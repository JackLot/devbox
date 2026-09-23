# Devbox launch checklist

Work top to bottom. Laptop commands run from the repo root (`~/dev/devbox`).
Each command block says where it runs:

- **laptop**: your Mac terminal
- **ssm**: admin shell on the box, opened with `aws ssm start-session --target "$INSTANCE_ID"` (later: `devbox ssm`)
- **devbox**: `ssh devbox`, as the unprivileged `dev` user

Shell variables used throughout (laptop):

```bash
export AWS_REGION=us-east-1          # pick your region
export AWS_PROFILE=admin             # sections 2-9; section 9 makes "devbox" the default
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

---

## 1. Laptop prerequisites (MacOS)

- [ ] AWS CLI v2: `brew install awscli`
- [ ] Session Manager plugin: `brew install --cask session-manager-plugin`
- [ ] Tailscale macOS app: `brew install --cask tailscale-app`, open it, sign in from the menu bar icon (this creates your tailnet if you don't have one), and approve the VPN prompt.
- [ ] **MagicDNS enabled** in the web admin console (login.tailscale.com/admin/dns; on by default for new tailnets). It makes `devbox` resolve as a hostname from your laptop.
- [ ] A dedicated SSH key with a passphrase, stored in the macOS keychain:
  ```bash
  ssh-keygen -t ed25519 -f ~/.ssh/devbox_ed25519 -C devbox
  ssh-add --apple-use-keychain ~/.ssh/devbox_ed25519
  ```

## 2. AWS account hardening (one-time)

Root user (console.aws.amazon.com > Root user > account name > Security credentials):

- [ ] MFA assigned. Add two devices (e.g. Touch ID passkey + authenticator app) so losing one doesn't lock you out.
- [ ] Access keys list is **empty**; delete any.
- [ ] The email account behind root has MFA too (root password resets go through it).
- [ ] Account (top right) > Account > **IAM user and role access to Billing information > Activate**. This is root-only, and without it your SSO sign-in can't see budgets or costs.
- [ ] Sign out of root. Everything below uses your Identity Center sign-in.

IAM Identity Center (short-lived SSO credentials instead of stored access keys):

- [ ] Console > IAM Identity Center > **Enable**, in the region you picked. This wraps your account in an AWS Organization as its "management account": still one account, same ID, same resources.
- [ ] Settings > Authentication: require MFA every sign-in. The access portal session length set here is how long `aws sso login` lasts (default 8 hours).
- [ ] Users > **Add user** (you). If the invite didn't prompt for a password, open the user > **Reset password** > one-time password, then sign in at the access portal URL (Settings) in a private window. Set a password and register MFA.
- [ ] Permission sets > Create > Predefined > **AdministratorAccess**. For setup work only.
- [ ] Permission sets > Create > Custom > Inline policy: paste [`iam/laptop-policy.json`](iam/laptop-policy.json), name it **`DevboxOperator`**. For everyday use: start/stop/describe the devbox and open SSM sessions to it, nothing else. You can do this signed in through the portal as AdministratorAccess; root isn't needed.
- [ ] AWS accounts > your account > Assign users or groups > your user > **both** permission sets.

Laptop profiles (one SSO sign-in, two profiles):

- [ ] Run `aws configure sso` (session name `personal`, your access portal URL, your region, AdministratorAccess, profile name `admin`), then add the `devbox` profile by hand. `~/.aws/config` should end up as:
  ```ini
  [sso-session personal]
  sso_start_url = https://d-xxxxxxxxxx.awsapps.com/start
  sso_region = us-east-1
  sso_registration_scopes = sso:account:access

  [profile admin]
  sso_session = personal
  sso_account_id = 123456789012
  sso_role_name = AdministratorAccess
  region = us-east-1

  [profile devbox]
  sso_session = personal
  sso_account_id = 123456789012
  sso_role_name = DevboxOperator
  region = us-east-1
  ```
- [ ] Delete any old static keys: remove the `[default]` block from `~/.aws/credentials` (or the file, if that's all it has).
- [ ] `aws sso login --sso-session personal`, then `aws sts get-caller-identity --profile admin` and `--profile devbox` both succeed (role names `AWSReservedSSO_AdministratorAccess_...` and `AWSReservedSSO_DevboxOperator_...`).
- [ ] Keep `AWS_PROFILE=admin` only in the terminal you use for this checklist. Section 9 makes `devbox` the default everywhere else.

Account defaults (admin profile):

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

- [ ] Tailnet policy: admin console (https://login.tailscale.com/admin) > **Access controls** > **JSON editor**. Replace the default allow-all rule (`"src": ["*"], "dst": ["*"]`), which would let the devbox reach your laptop, and keep everything else in the file (e.g. the default `"ssh"` section):
  ```jsonc
  {
    "tagOwners": {
      "tag:devbox": ["autogroup:admin"],
    },
    "grants": [
      // Your own devices can reach each other (replaces the default allow-all).
      { "src": ["autogroup:member"], "dst": ["autogroup:self"], "ip": ["*"] },
      // Your devices can reach the devbox on any port (SSH + dev servers).
      { "src": ["autogroup:member"], "dst": ["tag:devbox"], "ip": ["*"] },
      // Deliberately no grant with src tag:devbox: the box can't open
      // connections to your laptop or other devices.
    ],
  }
  ```
  Save the policy **before** generating the auth key: a key can only carry `tag:devbox` once `tagOwners` declares it.
- [ ] Generate an auth key (Settings > Keys, https://login.tailscale.com/admin/settings/keys): **Reusable off, Ephemeral off, Pre-approved on, Tags `tag:devbox`, Expiration 1 day**. Tagged nodes never hit key expiry, so the box won't drop off the tailnet after 180 days.
- [ ] Store it in Parameter Store without it touching shell history (laptop). Input is hidden, so paste **once** and press Enter; the check refuses anything that isn't exactly one key (e.g. pasted twice):
  ```bash
  printf 'Paste the Tailscale auth key ONCE, then Enter: '; read -rs TS_KEY; echo
  if [[ $TS_KEY == tskey-auth-* && $TS_KEY != *tskey-auth-*tskey-auth-* ]]; then
    aws ssm put-parameter --name /devbox/tailscale-authkey --type SecureString \
      --value "$TS_KEY" --overwrite && echo "stored (${#TS_KEY} chars)"
  else
    echo "not stored: that isn't a single tskey-auth-... key"
  fi
  unset TS_KEY
  ```
  Expect about 60 characters.

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
- [ ] The laptop never gets these permissions. Its everyday access is the `DevboxOperator` permission set from section 2.

## 5. Security group (no inbound) and subnet

A security group is a stateful firewall AWS enforces outside the OS: replies to connections the box opens (Tailscale, SSM, dnf, GitHub, model APIs) are allowed back automatically, and nothing on the internet can open a new connection in.

laptop:
```bash
VPC_ID=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
SG_ID=$(aws ec2 create-security-group --group-name devbox \
  --description "devbox - no inbound" --vpc-id "$VPC_ID" \
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Name,Value=devbox}]' \
  --query GroupId --output text)
aws ec2 describe-security-groups --group-ids "$SG_ID" \
  --query 'SecurityGroups[0].[IpPermissions,IpPermissionsEgress[0].IpProtocol]'
```

- [ ] The last command prints `[[], "-1"]`: no inbound rules, outbound allow-all (Tailscale, SSM, package repos, GitHub, model APIs all need it). Restricting outbound adds little (exfiltration would use 443 anyway) and breaks dnf/npm/Tailscale relays in confusing ways.
- [ ] Don't use the VPC's `default` group (it admits all traffic from other members), and **never** add an inbound rule to this one.

Pin the zone. An instance (and its EBS volume) stays in the zone it launches in, and not every zone offers every type (in this account, `us-east-1e` has no t4g or m7g). Pick one that offers today's type and the ones you might resize to:

```bash
aws ec2 describe-instance-type-offerings --location-type availability-zone \
  --filters Name=instance-type,Values=t4g.small,t4g.xlarge,m7g.xlarge \
  --query 'InstanceTypeOfferings[].[Location,InstanceType]' --output text | sort
AZ=us-east-1a                                   # a zone listed for all three
SUBNET_ID=$(aws ec2 describe-subnets \
  --filters Name=default-for-az,Values=true Name=availability-zone,Values="$AZ" \
  --query 'Subnets[0].SubnetId' --output text)
echo "$SUBNET_ID"
```

- [ ] `SUBNET_ID` is set (a `subnet-...` id). Section 7 launches into it.

## 6. SSH key pair

laptop:
```bash
aws ec2 import-key-pair --key-name devbox \
  --public-key-material fileb://~/.ssh/devbox_ed25519.pub
```

- [ ] Imported. The bootstrap copies this key to `dev`; `ec2-user` SSH is disabled (`AllowUsers dev`).

## 7. Launch

Two ways to launch the same instance: **Option A (console)** or **Option B (CLI)**. Whichever you use, these are the settings that matter:

| Setting | Why |
|---|---|
| AMI: standard AL2023, 64-bit Arm | Standard (not minimal) AL2023 ships the hibernation agent, AWS CLI and SSM agent |
| Hibernation enabled | **Can only be set at launch.** Without it, auto-hibernate can never work |
| IMDSv2 required, hop limit 1 | Containers and SSRF'd dev servers can't reach instance credentials |
| Instance metadata tags enabled | Lets bootstrap read the Name tag from IMDS (no extra IAM). Safe: hop limit 1, and Name is not a secret |
| 40 GB gp3, encrypted | Hibernation requires encryption. 40 GB = OS + projects + 4 GB hibernation image + 2 GB swapfile |
| Termination protection | A stray terminate can't delete the box |
| Subnet from section 5 | Pins the zone, so the launch never lands in one without t4g |
| Security group `devbox` | No inbound rules |
| `Name=devbox` tag on instance and volume | The IAM policies and the laptop helper find the instance by it |

Get the AMI id to compare against (laptop):
```bash
AMI_ID=$(aws ssm get-parameter \
  --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64 \
  --query Parameter.Value --output text)
echo "$AMI_ID"
```

### Option A: console

Console, signed in through the access portal as AdministratorAccess, region **US East (N. Virginia) us-east-1** (top right). EC2 > Instances > **Launch instances**. Only the fields listed here change; leave everything else at its default.

- [ ] **Name and tags**: Name exactly `devbox`. The IAM policies, the bootstrap preflight and the laptop helper match this exact string; `my devbox` breaks auto-hibernate and `devbox up`.
- [ ] **Tag the volume too**: still in **Name and tags**, click **Add additional tags**. The `Name` / `devbox` row appears with a **Resource types** dropdown; select **Volumes** in addition to **Instances**. Otherwise only the instance is tagged.
- [ ] **Application and OS Images**: Quick Start > **Amazon Linux** > **Amazon Linux 2023 AMI** (not "minimal"), Architecture **64-bit (Arm)**. The AMI id shown under the name must equal `$AMI_ID`; if it doesn't, paste `$AMI_ID` into the AMI search box and pick that one.
- [ ] **Instance type**: `t4g.small`.
- [ ] **Key pair (login)**: `devbox`.
- [ ] **Network settings > Edit**:
  - VPC: the default VPC
  - Subnet: the one in your section 5 zone (the id matches `$SUBNET_ID`)
  - Auto-assign public IP: **Enable** (needed for outbound internet; the security group keeps inbound closed)
  - Firewall: **Select existing security group > `devbox`**. The wizard defaults to *Create security group* with **SSH open to 0.0.0.0/0**. Do not launch with that.
- [ ] **Configure storage**: `40` GiB `gp3`. Click **Advanced**, expand the volume: **Encrypted** = Encrypted (KMS key: default `aws/ebs`), **Delete on termination** = Yes.
- [ ] **Advanced details**:
  - IAM instance profile: `devbox-instance`
  - Termination protection: **Enable**
  - Stop - Hibernate behavior: **Enable** (can't be changed after launch; the console requires the encrypted root volume set above)
  - Credit specification: **Unlimited**
  - Metadata accessible: Enabled
  - Metadata version: **V2 only (token required)**
  - Metadata response hop limit: **1**
  - Allow tags in metadata: **Enable**
  - User data: **Choose file** > `ec2/bootstrap.sh`. Leave "User data has already been base64 encoded" unticked.
- [ ] **Summary** panel: 1 instance, then **Launch instance**.
- [ ] Copy the instance id (`i-...`) from the success banner, then in your terminal:
  ```bash
  INSTANCE_ID=i-xxxxxxxxxxxxxxxxx
  ```

### Option B: CLI

laptop (uses `$AMI_ID` from above and `$SG_ID` / `$SUBNET_ID` from section 5):
```bash
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type t4g.small \
  --key-name devbox \
  --subnet-id "$SUBNET_ID" \
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

### After launch (both options)

- [ ] Confirm the launch settings took (laptop):
  ```bash
  aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --query \
    'Reservations[0].Instances[0].[ImageId,Placement.AvailabilityZone,HibernationOptions.Configured,MetadataOptions.HttpTokens,MetadataOptions.HttpPutResponseHopLimit,MetadataOptions.InstanceMetadataTags,SecurityGroups[0].GroupName]'
  aws ec2 describe-volumes --filters Name=attachment.instance-id,Values="$INSTANCE_ID" \
    --query 'Volumes[0].[Size,VolumeType,Encrypted,Tags[?Key==`Name`]|[0].Value]'
  ```
  Expect: `$AMI_ID`, your section 5 zone, `True`, `required`, `1`, `enabled`, `devbox`; then `40`, `gp3`, `true`, `devbox`.
- [ ] If the volume's Name shows `null`, tag it in place (no relaunch needed). Console: the instance > **Storage** tab > click the volume id > **Tags** > **Manage tags** > Add `Name` = `devbox` > Save. Or CLI:
  ```bash
  VOL_ID=$(aws ec2 describe-volumes --filters Name=attachment.instance-id,Values="$INSTANCE_ID" \
    --query 'Volumes[0].VolumeId' --output text)
  aws ec2 create-tags --resources "$VOL_ID" --tags Key=Name,Value=devbox
  ```
  The instance's own Name tag can be fixed the same way (`--resources "$INSTANCE_ID"`); it must be exactly `devbox`. The volume tag is only for identification and backups (section 13), so it isn't critical; the instance tag is.
- [ ] If metadata tags show `disabled`, fix it in place (no relaunch needed): `aws ec2 modify-instance-metadata-options --instance-id "$INSTANCE_ID" --instance-metadata-tags enabled`. Anything else wrong (above all hibernation `False` or an unencrypted volume) means terminate and relaunch: those can't be changed later.

## 8. Watch the bootstrap

No setup on the box is needed to watch the bootstrap: AL2023 ships the SSM agent, the instance role grants SSM, and the laptop has the session manager plugin from section 1. The agent takes a minute or two to register after boot. Three ways in, least to most access:

- **No connection at all**: EC2 console > the instance > Actions > Monitor and troubleshoot > **Get system log** (or `aws ec2 get-console-output --instance-id "$INSTANCE_ID" --latest --output text`). The bootstrap's `==>` progress lines and any `!!! WARNING` show up there.
- **Browser shell**: EC2 console > the instance > **Connect** > **Session Manager** tab > Connect.
- **Laptop shell**: `aws ssm start-session --target "$INSTANCE_ID"` (check it's registered first: `aws ssm describe-instance-information --query 'InstanceInformationList[].[InstanceId,PingStatus]'` shows `Online`).

ssm:
```bash
sudo cloud-init status --wait
sudo tail -n 40 /var/log/devbox-bootstrap.log
sudo journalctl -u hibinit-agent --no-pager | tail -n 20
```

- [ ] Log ends with `Bootstrap complete` and contains no `!!! WARNING` lines.
- [ ] hibinit-agent log shows the swap file created and the resume offset set, with no "Insufficient disk space".
- [ ] Reboot once, so any kernel installed by the bootstrap's upgrade is running (this also tests the reboot path): `sudo reboot`

If the log shows `tailscale up failed` or `invalid key`, re-store the key (section 3; a single-use key that was rejected was never consumed) and re-run the bootstrap. The rest of the setup still completes without Tailscale, and SSM keeps working.

If the bootstrap failed partway, fix the cause and re-run it (it is idempotent):
`sudo bash /var/lib/cloud/instance/scripts/part-001`

## 9. Wire up the laptop

- [ ] Delete the auth key parameter (the key is single-use, this is hygiene):
  ```bash
  aws ssm delete-parameter --name /devbox/tailscale-authkey
  ```
- [ ] Tailscale admin console shows `devbox` with `tag:devbox` and "Expiry disabled".
- [ ] Make the least-privilege profile the default for everything on the laptop (coding agents included), and keep admin opt-in:
  ```bash
  echo 'export AWS_PROFILE=devbox' >> ~/.zshrc && exec zsh
  aws sts get-caller-identity --query Arn --output text   # ends in .../AWSReservedSSO_DevboxOperator_...
  ```
  Later admin work: `aws --profile admin ...`. When `ssh devbox` can't wake the box because the SSO session expired, run `aws sso login --sso-session personal`.
- [ ] Append [`laptop/ssh_config`](laptop/ssh_config) to `~/.ssh/config`.
- [ ] Put the helper on your PATH:
  ```bash
  mkdir -p ~/.local/bin && ln -sf ~/dev/devbox/ec2/laptop/devbox ~/.local/bin/devbox
  ```
- [ ] `devbox status` prints the instance id, `running`, `t4g.small`.
- [ ] `ssh devbox` lands you in `/home/dev`.

Negative checks (all must fail):

- [ ] `ssh ec2-user@devbox` is refused (`Permission denied`).
- [ ] The default profile can't do admin things: `aws iam list-roles` fails with `AccessDenied`.
- [ ] `ssh -A devbox 'ssh-add -l'` reports no agent (forwarding refused server-side).
- [ ] The public IP is dark:
  ```bash
  PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
  nc -z -G 5 "$PUBLIC_IP" 22 && echo "EXPOSED" || echo "closed, good"
  ```
- [ ] `devbox: sudo -n true` fails (no sudo for the agent user).

Lock down launching (after the checks above pass):

- [ ] IAM Identity Center > Permission sets > **AdministratorAccess** > Inline policy > paste [`iam/admin-no-launch-policy.json`](iam/admin-no-launch-policy.json). An explicit deny wins, so no one can launch instances (CLI or console, including spot and fleet requests) until this is deliberately removed; removing it is itself a logged action. Resizing, start/stop and hibernate are unaffected. SCPs can't do this: they never apply to the management account.
- [ ] Check the deny works for **admin** (a fresh sign-in picks up the change): `aws sso login --sso-session personal`, then `aws --profile admin ec2 run-instances --dry-run --image-id "$AMI_ID" --instance-type t4g.small` fails with `UnauthorizedOperation`, not `DryRunOperation`.
- [ ] Remove `[profile admin]` from `~/.aws/config`. The laptop CLI (and any agent on it) then only has `DevboxOperator`. When you need admin later, re-add the profile or use the console through the access portal.

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
- [ ] Dotfiles applied (devbox): the prompt matches the laptop's (git branch icon, worktree tag), `echo $SHELL` is `/bin/zsh`, `tmux` shows the Catppuccin bar with prefix `C-a`, and `nvim` opens with your plugins (language servers finish installing on first open). DNS works: `getent hosts github.com` resolves.
- [ ] Headless browser works (devbox, as `dev`):
  ```bash
  mkdir -p ~/pwtest && cd ~/pwtest && npm init -y >/dev/null && npm install playwright && npx playwright install chromium
  node -e "const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();const p=await b.newPage();await p.goto('https://example.com');console.log(await p.title());await b.close()})()"
  ```
  Prints `Example Domain`. The "OS not officially supported" warning during install is expected on AL2023; the bootstrap installs the libraries it needs. Then `rm -rf ~/pwtest`.

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
