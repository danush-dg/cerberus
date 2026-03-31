"""
scripts/seed_sandbox.py — Creates 'waste' and 'risk' in the GCP sandbox for demo.
"""

import os
import sys
import time
from google.cloud import compute_v1
from dotenv import load_dotenv


def wait_for_operation(operation, label):
    try:
        operation.result()  # Wait until done
        if operation.error:
            print(f"{label} failed ❌: {operation.error}")
            return False
        print(f"{label} completed ✅")
        return True
    except Exception as e:
        print(f"{label} exception ❌: {e}")
        return False


def main():
    load_dotenv()

    project_id = os.environ.get("GCP_PROJECT_ID")
    zone = os.environ.get("GCP_ZONE", "asia-south1-b")
    region = zone.rsplit("-", 1)[0]

    if not project_id:
        print("Error: GCP_PROJECT_ID not set")
        sys.exit(1)

    print(f"\n--- Seeding Sandbox: Project '{project_id}' ---\n")

    # ---------------------------------------------------------------------
    # 1. COST STORY → Idle VM
    # ---------------------------------------------------------------------
    vm_name = f"cerberus-idle-vm-{int(time.time())}"
    print(f"Creating Idle VM: {vm_name}")

    instance_client = compute_v1.InstancesClient()

    instance = compute_v1.Instance()
    instance.name = vm_name
    instance.machine_type = f"zones/{zone}/machineTypes/e2-micro"

    instance.labels = {
        "owner": "bob-departed-engineer",
        "created-by": "bob-departed-engineer",
        "team": "ml-platform"
    }

    # Network
    network = compute_v1.NetworkInterface()
    network.network = "global/networks/default"

    access_config = compute_v1.AccessConfig()
    access_config.type_ = "ONE_TO_ONE_NAT"
    network.access_configs = [access_config]

    instance.network_interfaces = [network]

    # Boot Disk
    init_params = compute_v1.AttachedDiskInitializeParams()
    init_params.source_image = "projects/debian-cloud/global/images/family/debian-11"
    init_params.disk_size_gb = 10

    boot_disk = compute_v1.AttachedDisk()
    boot_disk.boot = True
    boot_disk.auto_delete = True
    boot_disk.initialize_params = init_params

    instance.disks = [boot_disk]

    try:
        op = instance_client.insert(
            project=project_id,
            zone=zone,
            instance_resource=instance
        )
        vm_created = wait_for_operation(op, "VM creation")
    except Exception as e:
        print(f"VM creation failed ❌: {e}")
        vm_created = False

    # ---------------------------------------------------------------------
    # 2. SECURITY STORY → Sensitive Disk
    # ---------------------------------------------------------------------
    disk_name = f"cerberus-sensitive-disk-{int(time.time())}"
    print(f"\nCreating Sensitive Disk: {disk_name}")

    disk_client = compute_v1.DisksClient()

    disk = compute_v1.Disk()
    disk.name = disk_name
    disk.size_gb = 50
    disk.labels = {
        "data-classification": "sensitive",
        "owner": "unknown"
    }

    try:
        op = disk_client.insert(
            project=project_id,
            zone=zone,
            disk_resource=disk
        )
        disk_created = wait_for_operation(op, "Disk creation")
    except Exception as e:
        print(f"Disk creation failed ❌: {e}")
        disk_created = False

    # ---------------------------------------------------------------------
    # 3. COST STORY → Unused Static IP
    # ---------------------------------------------------------------------
    ip_name = f"cerberus-unused-ip-{int(time.time())}"
    print(f"\nReserving Static IP: {ip_name}")

    address_client = compute_v1.AddressesClient()

    address = compute_v1.Address()
    address.name = ip_name

    try:
        op = address_client.insert(
            project=project_id,
            region=region,
            address_resource=address
        )
        ip_created = wait_for_operation(op, "IP reservation")
    except Exception as e:
        print(f"IP reservation failed ❌: {e}")
        ip_created = False

    # ---------------------------------------------------------------------
    # FINAL STATUS
    # ---------------------------------------------------------------------
    print("\n--- Final Status ---")

    if vm_created and disk_created and ip_created:
        print("✅ Sandbox seeded successfully!")
    else:
        print("⚠️ Sandbox partially seeded (check errors above)")

    print("\nYou can now run your Analyze step.")


if __name__ == "__main__":
    main()