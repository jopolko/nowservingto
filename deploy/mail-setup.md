# Self-hosted mail from the VPS

Goal: send DKIM/SPF/DMARC-aligned mail from `alerts@nowservingto.com`
out of the DigitalOcean droplet `143.110.236.86`. No Resend, no SendGrid
- just Postfix + OpenDKIM with proper DNS.

**Reality check.** DigitalOcean IPv4 ranges are on a few spam-score
lists; Gmail will accept us once DKIM/SPF/DMARC all pass; Outlook /
Hotmail will likely junk us for the first few weeks regardless. Build
a steady, low-volume reputation and they'll relent. If a particular
domain blackholes us hard, escalate via their postmaster portal.

The chain:

```
alerts_server.py ──smtplib──▶ Postfix (127.0.0.1:25)
                                  │  outbound port 25
                                  ▼
                        OpenDKIM milter signs as
                        d=nowservingto.com s=mail
                                  │
                                  ▼
                            recipient MX
```

---

## 1. DNS records (Cloudflare, all DNS-only / grey-cloud unless noted)

Replace `143.110.236.86` if the droplet IP changes.

| Type   | Name                              | Value                                                                                                                                                                  | Proxy | TTL  |
|--------|-----------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------|------|
| A      | `mail`                            | `143.110.236.86`                                                                                                                                                       | DNS only | Auto |
| MX     | `@` (nowservingto.com)            | `mail.nowservingto.com` priority `10`                                                                                                                                  | n/a   | Auto |
| TXT    | `@`                               | `v=spf1 ip4:143.110.236.86 -all`                                                                                                                                       | n/a   | Auto |
| TXT    | `_dmarc`                          | `v=DMARC1; p=none; rua=mailto:dmarc@nowservingto.com; ruf=mailto:dmarc@nowservingto.com; fo=1; aspf=s; adkim=s`                                                        | n/a   | Auto |
| TXT    | `mail._domainkey`                 | (paste from `/etc/opendkim/keys/nowservingto.com/mail.txt` after step 3 - see DKIM section)                                                                            | n/a   | Auto |

Notes:
- **SPF**: `-all` (hard fail). Only this IP may send for the domain. If
  you ever route through Substack/Mailgun later, add their include
  before changing `-all` to `~all`.
- **DMARC `p=none`**: monitoring-only for the first 2-4 weeks. Once
  Google's Postmaster Tools shows DKIM/SPF aligned ≥99%, switch to
  `p=quarantine` then `p=reject`.
- **MX**: we're outbound-only, but publishing MX makes us look like a
  real domain to receivers + lets DMARC reports route back. The
  `mail.nowservingto.com` host doesn't need a working IMAP/POP3 -
  just needs to accept SMTP on 25 (Postfix does by default).
- **PTR (rDNS)** is set by DigitalOcean, not Cloudflare - see step 4.

---

## 2. Install Postfix + OpenDKIM on the VPS

SSH in (`ssh -p 34522 -i ~/.ssh/nowservingto_deploy john@143.110.236.86`),
then:

```bash
sudo apt update
sudo DEBIAN_FRONTEND=noninteractive apt install -y postfix opendkim opendkim-tools mailutils
```

Postfix will prompt for "General type of mail configuration" - choose
**Internet Site**, and set the system mail name to `nowservingto.com`.
If apt ran non-interactively, fix afterward:

```bash
sudo dpkg-reconfigure postfix
```

---

## 3. Configure Postfix (`/etc/postfix/main.cf`)

Append (or replace existing lines for these keys):

```
myhostname = mail.nowservingto.com
mydomain = nowservingto.com
myorigin = $mydomain
mydestination = $myhostname, localhost.$mydomain, localhost
inet_interfaces = loopback-only
inet_protocols = ipv4

# Submit-only relay rules - only loopback clients (our alerts service)
# may inject mail. No open-relay risk.
smtpd_relay_restrictions = permit_mynetworks, reject_unauth_destination

# DKIM signing via OpenDKIM milter on 127.0.0.1:8891
milter_default_action = accept
milter_protocol = 6
smtpd_milters = inet:127.0.0.1:8891
non_smtpd_milters = $smtpd_milters

# Opportunistic TLS to remote MTAs
smtp_tls_security_level = may
smtp_tls_loglevel = 1
smtp_tls_CAfile = /etc/ssl/certs/ca-certificates.crt
```

Then reload:

```bash
sudo systemctl reload postfix
```

---

## 4. Configure OpenDKIM

```bash
sudo mkdir -p /etc/opendkim/keys/nowservingto.com
cd /etc/opendkim/keys/nowservingto.com
sudo opendkim-genkey -b 2048 -d nowservingto.com -D . -s mail -v
sudo chown opendkim:opendkim mail.private
sudo chmod 600 mail.private
```

Edit `/etc/opendkim.conf` - replace its contents with:

```
Syslog                  yes
SyslogSuccess           yes
UMask                   002
Mode                    sv
Canonicalization        relaxed/relaxed
Domain                  nowservingto.com
KeyFile                 /etc/opendkim/keys/nowservingto.com/mail.private
Selector                mail
Socket                  inet:8891@localhost
PidFile                 /run/opendkim/opendkim.pid
OversignHeaders         From
SignatureAlgorithm      rsa-sha256
UserID                  opendkim:opendkim
```

Make sure opendkim's user is in postfix's group so the milter socket
works across uid boundaries:

```bash
sudo gpasswd -a postfix opendkim
sudo systemctl enable --now opendkim
sudo systemctl restart postfix
```

Now publish the public key. `cat /etc/opendkim/keys/nowservingto.com/mail.txt`
prints something like:

```
mail._domainkey IN TXT ( "v=DKIM1; h=sha256; k=rsa; "
  "p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxx...xx"
  "xx...xx" ) ; ----- DKIM key mail for nowservingto.com
```

Paste *just the `v=DKIM1; ... p=...` body* (no quotes, no parens,
concatenated as one string) into Cloudflare's TXT value field for
`mail._domainkey`. Cloudflare auto-splits long TXT records at the
255-byte boundary.

---

## 5. Set rDNS (PTR) at DigitalOcean

DO derives the PTR from the *droplet name*. In the DO dashboard:

1. Droplets → click the droplet → click the droplet's name at the top.
2. Rename it to `mail.nowservingto.com`.
3. Wait ~30 minutes, then verify on the VPS: `host 143.110.236.86`
   should return `mail.nowservingto.com`.

Also set the system hostname so Postfix's HELO matches:

```bash
sudo hostnamectl set-hostname mail.nowservingto.com
```

The Postfix `myhostname` directive (set in step 3) already references
this; reload Postfix again after the change.

---

## 6. Smoke-test

From the VPS:

```bash
echo -e "Subject: dkim smoke test\n\nhello" \
  | /usr/sbin/sendmail -f alerts@nowservingto.com mjopolko@gmail.com
sudo tail -n 50 /var/log/mail.log
```

In Gmail, "Show original" on the received message should show:

```
SPF:     PASS with IP 143.110.236.86
DKIM:    'PASS' with domain nowservingto.com
DMARC:   'PASS'
```

For an objective score, send to `test-XXXXX@mail-tester.com` and visit
the URL it gives you. Aim for ≥9/10 before opening real subscriptions.

---

## 7. Cleanup once it's working

- Add a tiny mailbox alias for `dmarc@` so DMARC aggregate reports
  land somewhere readable. Easiest: in `/etc/aliases`, add
  `dmarc: mjopolko@gmail.com` then `sudo newaliases`.
- After 2-4 weeks of clean DMARC reports, flip `_dmarc` from
  `p=none` to `p=quarantine`, then later to `p=reject`.
- If volume ever spikes (>500/day), consider rotating to a second
  selector (`mail2._domainkey`) so you can swap keys without a brief
  outage.
