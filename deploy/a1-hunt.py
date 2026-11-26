#!/usr/bin/env python3
"""Keep trying to launch a free-tier Ampere A1 VM (4 OCPU / 24 GB) until one sticks.

Oracle's free A1 pool is usually "Out of host capacity", so this runs from cron
on the current portal VM every few minutes. It authenticates as the VM itself
(instance principals), so no API key lives on disk. One-time console setup:

  1. Identity > Dynamic groups > create `portal-vm` with rule
       instance.id = '<this VM's instance OCID>'
  2. Identity > Policies (root compartment) > create `portal-vm-a1-hunt`:
       Allow dynamic-group portal-vm to manage instance-family in tenancy
       Allow dynamic-group portal-vm to use virtual-network-family in tenancy
       Allow dynamic-group portal-vm to read app-catalog-listing in tenancy

Install on the VM (see deploy/RUNBOOK.md "A1 capacity hunt"):
  python3 -m venv ~/a1-hunt-venv && ~/a1-hunt-venv/bin/pip install oci
  crontab: */5 * * * * ~/a1-hunt-venv/bin/python ~/a1-hunt.py >> ~/a1-hunt.log 2>&1

Once an instance launches it writes ~/a1-hunt.done and every later run exits
immediately. A success email goes out through the portal's Zoho SMTP settings
(backend/.env) to NOTIFY_TO, or SMTP_USER when that is unset.
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import oci

HOME = Path.home()
DONE = HOME / "a1-hunt.done"
ENV_FILE = HOME / "MTR_Portal" / "backend" / ".env"
SSH_KEYS = HOME / ".ssh" / "authorized_keys"

OCPUS = float(os.environ.get("A1_OCPUS", "4"))
MEMORY_GB = float(os.environ.get("A1_MEMORY_GB", "24"))
BOOT_GB = int(os.environ.get("A1_BOOT_GB", "100"))  # free tier: 200 GB total block storage
NAME = os.environ.get("A1_NAME", "mtr-portal-a1")
OS_VERSION = os.environ.get("A1_OS_VERSION", "22.04")


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z {msg}", flush=True)


def metadata(path: str):
    req = urllib.request.Request(
        f"http://169.254.169.254/opc/v2/{path}", headers={"Authorization": "Bearer Oracle"}
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def notify(subject: str, body: str) -> None:
    env = read_env(ENV_FILE)
    host, user, pw = env.get("SMTP_HOST"), env.get("SMTP_USER"), env.get("SMTP_PASSWORD")
    to = os.environ.get("NOTIFY_TO") or user
    if not (host and user and pw and to):
        log("no SMTP settings; skipping email")
        return
    msg = EmailMessage()
    msg["From"] = env.get("MAIL_FROM_ADDRESS") or user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    port = int(env.get("SMTP_PORT") or 465)
    ctx = ssl.create_default_context()
    try:
        if env.get("SMTP_SSL", "true").lower() in ("1", "true", "yes") or port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
                s.login(user, pw)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ctx)
                s.login(user, pw)
                s.send_message(msg)
        log(f"emailed {to}")
    except Exception as e:  # never let mail failure hide a successful launch
        log(f"email failed: {e}")


def main() -> int:
    if DONE.exists():
        return 0

    me = metadata("instance/")
    signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    cfg = {"region": me["region"]}
    compute = oci.core.ComputeClient(cfg, signer=signer)
    network = oci.core.VirtualNetworkClient(cfg, signer=signer)
    identity = oci.identity.IdentityClient(cfg, signer=signer)

    compartment = me["compartmentId"]
    tenancy = compartment if compartment.startswith("ocid1.tenancy") else None
    vnic_id = metadata("vnics/")[0]["vnicId"]
    subnet_id = network.get_vnic(vnic_id).data.subnet_id

    # Already have one (e.g. launched by hand)? Stop hunting.
    for inst in compute.list_instances(compartment).data:
        if inst.shape == "VM.Standard.A1.Flex" and inst.lifecycle_state not in ("TERMINATED", "TERMINATING"):
            DONE.write_text(inst.id + "\n")
            log(f"A1 instance already exists: {inst.id}")
            return 0

    images = compute.list_images(
        compartment,
        operating_system="Canonical Ubuntu",
        operating_system_version=OS_VERSION,
        shape="VM.Standard.A1.Flex",
        sort_by="TIMECREATED",
        sort_order="DESC",
    ).data
    images = [i for i in images if "Minimal" not in i.display_name] or images
    if not images:
        log("no Ubuntu aarch64 image found")
        return 1
    image = images[0]

    ads = [ad.name for ad in identity.list_availability_domains(tenancy or compartment).data]
    ssh_keys = SSH_KEYS.read_text()

    for ad in ads:
        details = oci.core.models.LaunchInstanceDetails(
            availability_domain=ad,
            compartment_id=compartment,
            display_name=NAME,
            shape="VM.Standard.A1.Flex",
            shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                ocpus=OCPUS, memory_in_gbs=MEMORY_GB
            ),
            source_details=oci.core.models.InstanceSourceViaImageDetails(
                image_id=image.id, boot_volume_size_in_gbs=BOOT_GB
            ),
            create_vnic_details=oci.core.models.CreateVnicDetails(
                subnet_id=subnet_id, assign_public_ip=True
            ),
            metadata={"ssh_authorized_keys": ssh_keys},
        )
        try:
            inst = compute.launch_instance(details).data
        except oci.exceptions.ServiceError as e:
            log(f"{ad}: {e.status} {e.code}: {e.message}")
            continue
        DONE.write_text(inst.id + "\n")
        log(f"LAUNCHED {inst.id} in {ad} ({image.display_name})")
        notify(
            "MTR portal: free A1 VM secured (24 GB)",
            f"A {OCPUS:g} OCPU / {MEMORY_GB:g} GB Ampere A1 instance launched.\n\n"
            f"Instance: {inst.id}\nAD: {ad}\nImage: {image.display_name}\n\n"
            "It has the same SSH keys as the current VM. Public IP shows in the OCI "
            "console once it is RUNNING. Next step: migrate the portal onto it.",
        )
        return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except oci.exceptions.ServiceError as e:
        # Usually the dynamic group / policy is missing (404 NotAuthorizedOrNotFound).
        log(f"{e.operation_name}: {e.status} {e.code}: {e.message}")
        sys.exit(1)
