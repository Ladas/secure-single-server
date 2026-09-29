#!/usr/bin/env python3
"""Cloud-free tests of the AWS resource plan and mutation guard."""
import importlib.machinery
import importlib.util
import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("rhel_vm", str(ROOT / "scripts/aws/rhel-vm"))
spec = importlib.util.spec_from_loader(loader.name, loader)
vm = importlib.util.module_from_spec(spec)
loader.exec_module(vm)


class PlanTest(unittest.TestCase):
    def test_complete_plans_cover_each_scenario_and_hardware_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "test.pub"
            key.write_text("ssh-ed25519 synthetic-test-key\n")
            for scenario in ["all-in-one", "remote-gateway", "openshell-praxis"]:
                for arch, native, inference, instance, disk in [
                        ("amd64", "x86_64", "none", "m7i.2xlarge", 50),
                        ("arm64", "arm64", "none", "m7g.2xlarge", 50),
                        ("amd64", "x86_64", "cpu", "m7i.4xlarge", 100),
                        ("amd64", "x86_64", "gpu", "g6.2xlarge", 200)]:
                    args = self.settings(account_id="123456789012", arch=arch, inference=inference,
                        subnet_id="subnet-test", prefix="test-" + scenario, public_key=key,
                        scenario=scenario, allowed_cidr="192.0.2.1/32", region="eu-central-1",
                        state_file=Path(directory) / (scenario + arch + inference + ".json"))
                    vm.configure(args)
                    machine = {"MemoryInfo": {"SizeInMiB": 65536 if inference == "cpu" else 32768},
                               "ProcessorInfo": {"SupportedArchitectures": [native]}}
                    if inference == "gpu":
                        machine["GpuInfo"] = {"Gpus": [{"Name": "L4", "Manufacturer": "NVIDIA", "Count": 1,
                                                      "MemoryInfo": {"SizeInMiB": 23040}}]}
                    aws = vm.Aws(args.region, None, False)
                    responses = [
                        {"Account": args.account_id, "Arn": "arn:aws:iam::123456789012:user/test"},
                        {"InstanceTypes": [machine]},
                        {"Images": [{"ImageId": "ami-test", "CreationDate": "2026-09-01", "OwnerId": vm.OWNER,
                            "Architecture": native, "State": "available", "RootDeviceType": "ebs",
                            "BlockDeviceMappings": [{"DeviceName": "/dev/sda1", "Ebs": {}}],
                            "RootDeviceName": "/dev/sda1", "Name": f"RHEL-9.6_HVM-test-{native}-0-Hourly2-GP3"}]},
                        {"Subnets": [{"State": "available", "VpcId": "vpc-test", "AvailabilityZone": "eu-central-1a"}]},
                        {"InstanceTypeOfferings": [{"Location": "eu-central-1a"}]},
                        {"RouteTables": [{"Routes": [{"DestinationCidrBlock": "0.0.0.0/0",
                                                      "GatewayId": "igw-test", "State": "active"}]}]},
                        {"Reservations": []}, {"SecurityGroups": []}, {"KeyPairs": []}]
                    with patch.object(aws, "call", side_effect=responses) as calls, \
                            patch.object(vm.subprocess, "run"):
                        proposal = vm.plan(aws, args)
                    self.assertEqual(proposal["Architecture"], native)
                    self.assertEqual((proposal["Inference"], proposal["InstanceType"], proposal["VolumeGiB"]),
                                     (inference, instance, disk))
                    self.assertEqual(proposal["AvailabilityZone"], "eu-central-1a")
                    self.assertEqual(len(proposal["Ingress"]), 2 if scenario == "remote-gateway" else 1)
                    self.assertTrue(all(call.args[1] in vm.READS for call in calls.call_args_list))
                    self.assertFalse(args.state_file.exists())

    def settings(self, **overrides):
        return SimpleNamespace(**dict.fromkeys(vm.CONFIG_KEYS | {"config"}) | overrides)

    def test_config_defaults_and_explicit_overrides(self):
        for name, kind, machine, disk in (("no-vllm", "none", "m7i.2xlarge", 50),
                ("vllm-cpu", "cpu", "m7i.4xlarge", 100), ("vllm-gpu", "gpu", "g6.2xlarge", 200)):
            args = self.settings(config=ROOT / f"configs/aws/{name}.json", scenario="all-in-one")
            vm.configure(args)
            self.assertEqual((args.inference, args.instance_type, args.volume_gib), (kind, machine, disk))
        args = self.settings(config=ROOT / "configs/aws/vllm-gpu.json", scenario="remote-gateway",
                             instance_type="g6.4xlarge", volume_gib=300)
        vm.configure(args)
        self.assertEqual((args.scenario, args.inference, args.instance_type, args.volume_gib),
                         ("remote-gateway", "gpu", "g6.4xlarge", 300))
        args = self.settings(scenario="all-in-one", inference="cpu")
        vm.configure(args)
        self.assertEqual((args.instance_type, args.volume_gib), ("m7i.4xlarge", 100))
        args = self.settings(scenario="all-in-one", arch="arm64")
        vm.configure(args)
        self.assertEqual(args.instance_type, "m7g.2xlarge")

    def test_invalid_config_is_rejected_before_cloud_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "vm.json"
            for invalid in (["gpu"], {"access_key": "never-accept"}, {"volume_gib": True},
                    {"volume_gib": "200"}, {"scenario": "typo"}, {"inference": "cuda"},
                    {"arch": "x86_64"}, {"arch": "arm64", "inference": "cpu"},
                    {"inference": "gpu", "volume_gib": 100}, {"inference": "cpu", "volume_gib": 50},
                    {"volume_gib": 16385}, {"instance_type": ""}, {"ami_id": "bad"}):
                config.write_text(json.dumps({"scenario": "all-in-one", **invalid}
                                             if isinstance(invalid, dict) else invalid))
                with self.subTest(invalid=invalid), patch.object(vm.Aws, "call") as calls:
                    with self.assertRaises(ValueError):
                        vm.configure(self.settings(config=config))
                    calls.assert_not_called()

    def test_gpu_profile_accepts_only_one_full_l4(self):
        machine = {"MemoryInfo": {"SizeInMiB": 32768},
                   "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
                   "GpuInfo": {"Gpus": [{"Name": "L4", "Manufacturer": "NVIDIA", "Count": 1,
                                       "MemoryInfo": {"SizeInMiB": 23040}}]}}
        vm.validate_machine(machine, "x86_64", "gpu")
        for change in ({"Name": "A10G"}, {"Manufacturer": "AMD"}, {"Count": 4},
                       {"GpuPartitionSize": 0.5}, {"MemoryInfo": {"SizeInMiB": 12000}}):
            wrong = copy.deepcopy(machine)
            wrong["GpuInfo"]["Gpus"][0].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "full NVIDIA L4"):
                vm.validate_machine(wrong, "x86_64", "gpu")
        del machine["GpuInfo"]
        with self.assertRaises(ValueError):
            vm.validate_machine(machine, "x86_64", "gpu")
        for memory, arch in ((16384, "x86_64"), (32768, "arm64")):
            machine["MemoryInfo"]["SizeInMiB"] = memory
            with self.assertRaises(ValueError):
                vm.validate_machine(machine, arch, "cpu")

    def test_unavailable_type_in_subnet_zone_fails_without_mutation(self):
        aws = vm.Aws("eu-central-1", None, False)
        with patch.object(aws, "call", return_value={"InstanceTypeOfferings": []}) as calls:
            with self.assertRaisesRegex(ValueError, "not offered in eu-central-1b"):
                vm.check_offering(aws, "g6.2xlarge", "eu-central-1b")
            self.assertEqual(calls.call_args.kwargs["location_type"], "availability-zone")
            self.assertIn({"Name": "location", "Values": ["eu-central-1b"]}, calls.call_args.kwargs["filters"])

    def test_existing_journal_blocks_second_launch_before_aws(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            vm.save_state(state, {"ApplyStatus": "started"})
            argv = ["rhel-vm", "apply", "--region", "eu-central-1", "--account-id", "123456789012",
                    "--state-file", str(state), "--config", str(ROOT / "configs/aws/vllm-gpu.json"), "--scenario", "all-in-one",
                    "--prefix", "test-qwen", "--subnet-id", "subnet-test", "--public-key", "missing.pub",
                    "--allowed-cidr", "192.0.2.1/32"]
            with patch.object(vm.sys, "argv", argv), patch.object(vm.Aws, "call") as calls:
                with self.assertRaisesRegex(ValueError, "state file already exists"):
                    vm.main()
                calls.assert_not_called()

    def test_apply_requires_confirmation_of_current_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = ["rhel-vm", "apply", "--region", "eu-central-1", "--account-id", "123456789012",
                    "--state-file", str(Path(directory) / "state.json"),
                    "--config", str(ROOT / "configs/aws/vllm-gpu.json"), "--scenario", "all-in-one", "--instance-type", "g6.4xlarge",
                    "--prefix", "test-qwen", "--subnet-id", "subnet-test", "--public-key", "missing.pub",
                    "--allowed-cidr", "192.0.2.1/32"]
            with patch.object(vm.sys, "argv", argv), patch.object(vm, "plan", return_value={}) as plan, \
                    patch.object(vm, "apply_plan") as apply, patch("builtins.input", return_value="no"), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, "confirmation did not match"):
                    vm.main()
                self.assertEqual(plan.call_args.args[1].instance_type, "g6.4xlarge")
                apply.assert_not_called()

    def test_obsolete_batch_invocation_cannot_plan_or_launch_without_config(self):
        # A previously sourced helper ignores NAME CONFIG and invokes this old CLI.
        for mode in ("plan", "apply"):
            argv = ["rhel-vm", mode, "--region", "eu-central-1", "--account-id", "123456789012",
                    "--state-file", "/unused/state.json", "--scenario", "all-in-one",
                    "--prefix", "old-all-in-one", "--subnet-id", "subnet-test", "--public-key", "missing.pub",
                    "--allowed-cidr", "192.0.2.1/32"]
            with patch.object(vm.sys, "argv", argv), patch.object(vm.Aws, "call") as calls:
                with self.assertRaisesRegex(ValueError, "--config.*reload"):
                    vm.main()
                calls.assert_not_called()

    def test_public_ssh_is_explicit_and_does_not_open_https_or_backends(self):
        for scenario in vm.SCENARIOS:
            rules = vm.ingress(scenario, "192.0.2.1/32", ssh_access="public")
            self.assertEqual(rules[0]["IpRanges"], [{"CidrIp": "0.0.0.0/0"}])
            self.assertEqual([rule["FromPort"] for rule in rules],
                             [22, 8443] if scenario == "remote-gateway" else [22])
            if scenario == "remote-gateway":
                self.assertEqual(rules[1]["IpRanges"], [{"CidrIp": "192.0.2.1/32"}])
        self.assertEqual(len(vm.ingress("all-in-one", None, ssh_access="public")), 1)
        for scenario, cidr, access in (("remote-gateway", None, "public"),
                ("remote-gateway", "0.0.0.0/0", "public"), ("all-in-one", None, "restricted"),
                ("all-in-one", "192.0.2.1/32", "typo")):
            with self.subTest(scenario=scenario, cidr=cidr, access=access), self.assertRaises(ValueError):
                vm.ingress(scenario, cidr, ssh_access=access)

    def test_https_access_is_independent_and_remote_only(self):
        for ssh_access in ("restricted", "public"):
            for https_access in ("restricted", "public"):
                rules = vm.ingress("remote-gateway", "192.0.2.1/32", ssh_access, https_access)
                self.assertEqual([rule["FromPort"] for rule in rules], [22, 8443])
                self.assertEqual([rule["IpRanges"] for rule in rules], [
                    [{"CidrIp": "0.0.0.0/0" if access == "public" else "192.0.2.1/32"}]
                    for access in (ssh_access, https_access)])
        self.assertEqual(len(vm.ingress("remote-gateway", None, "public", "public")), 2)
        for scenario, cidr, ssh_access, https_access in (
                ("remote-gateway", None, "restricted", "public"),
                ("remote-gateway", "0.0.0.0/0", "restricted", "public"),
                ("remote-gateway", "192.0.2.1/32", "restricted", "typo"),
                ("all-in-one", "192.0.2.1/32", "restricted", "public")):
            with self.subTest(scenario=scenario, cidr=cidr), self.assertRaises(ValueError):
                vm.ingress(scenario, cidr, ssh_access, https_access)

    def test_https_access_config_and_override(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "vm.json"
            config.write_text(json.dumps({"scenario": "remote-gateway", "https_access": "public"}))
            args = self.settings(config=config)
            vm.configure(args)
            self.assertEqual(args.https_access, "public")
            self.assertEqual(args.ssh_access, "restricted")
            args = self.settings(config=config, https_access="restricted")
            vm.configure(args)
            self.assertEqual(args.https_access, "restricted")
            with self.assertRaisesRegex(ValueError, "https_access"):
                vm.configure(self.settings(config=config, https_access="typo"))
            with self.assertRaisesRegex(ValueError, "remote-gateway"):
                vm.configure(self.settings(config=config, scenario="all-in-one"))

    def test_ssh_access_config_and_override(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "vm.json"
            config.write_text(json.dumps({"scenario": "all-in-one", "ssh_access": "public"}))
            args = self.settings(config=config)
            vm.configure(args)
            self.assertEqual(args.ssh_access, "public")
            args = self.settings(config=config, ssh_access="restricted")
            vm.configure(args)
            self.assertEqual(args.ssh_access, "restricted")
            with self.assertRaisesRegex(ValueError, "ssh_access"):
                vm.configure(self.settings(config=config, ssh_access="typo"))

    def test_wrong_account_and_root_rejected(self):
        for identity in [{"Account": "000000000000", "Arn": "arn:aws:iam::000000000000:user/test"},
                         {"Account": "123456789012", "Arn": "arn:aws:iam::123456789012:root"}]:
            aws = vm.Aws("eu-central-1", None, False)
            with patch.object(aws, "call", return_value=identity), self.assertRaises(ValueError):
                vm.check_identity(aws, "123456789012")

    def test_ingress_is_explicit_and_scenario_specific(self):
        self.assertEqual([rule["FromPort"] for rule in vm.ingress("all-in-one", "192.0.2.1/32")], [22])
        self.assertEqual([rule["FromPort"] for rule in vm.ingress("remote-gateway", "192.0.2.1/32")], [22, 8443])
        self.assertEqual([rule["FromPort"] for rule in vm.ingress("openshell-praxis", "192.0.2.1/32")], [22])
        with self.assertRaises(ValueError):
            vm.ingress("typo", "192.0.2.1/32")
        for bad in ["0.0.0.0/0", "192.0.2.0/24", "::/0", "bad"]:
            with self.assertRaises(ValueError):
                vm.ingress("remote-gateway", bad)

    def test_missing_public_key_fails_before_aws_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(public_key=Path(directory) / "missing.pub")
            aws = vm.Aws("eu-central-1", None, False)
            with patch.object(aws, "call") as calls, self.assertRaisesRegex(ValueError, "public key.*aws_test_key"):
                vm.plan(aws, args)
            calls.assert_not_called()

    def test_read_only_guard_precedes_subprocess(self):
        aws = vm.Aws("eu-central-1", None, False)
        with patch.object(vm.subprocess, "run") as run:
            for service, action in [("ec2", "run-instances"), ("ec2", "create-security-group"),
                                    ("iam", "create-role"), ("ec2", "terminate-instances")]:
                with self.assertRaises(ValueError):
                    aws.call(service, action)
            run.assert_not_called()

    def test_architecture_and_ami(self):
        for architecture in ["x86_64", "arm64"]:
            image = {"OwnerId": vm.OWNER, "Architecture": architecture, "RootDeviceType": "ebs",
                     "RootDeviceName": "/dev/sda1", "BlockDeviceMappings": [{"DeviceName": "/dev/sda1", "Ebs": {}}],
                     "State": "available", "Name": f"RHEL-9.6_HVM-test-{architecture}-Hourly2-GP3"}
            vm.validate_image(image, architecture)
            with self.assertRaises(ValueError):
                vm.validate_image(image, "arm64" if architecture == "x86_64" else "x86_64")
            image["OwnerId"] = "untrusted"
            with self.assertRaises(ValueError):
                vm.validate_image(image, architecture)

    def test_image_cannot_add_unplanned_disks(self):
        image = {"OwnerId": vm.OWNER, "Architecture": "arm64", "RootDeviceType": "ebs",
                 "RootDeviceName": "/dev/sda1", "State": "available",
                 "Name": "RHEL-9.6_HVM-test-arm64-Hourly2-GP3"}
        for mappings in [[], [{"DeviceName": "/dev/sdb", "Ebs": {}}],
                         [{"DeviceName": "/dev/sda1", "Ebs": {}}, {"DeviceName": "/dev/sdb", "Ebs": {}}]]:
            with self.subTest(mappings=mappings), self.assertRaises(ValueError):
                vm.validate_image({**image, "BlockDeviceMappings": mappings}, "arm64")

    def test_state_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            vm.save_state(path, {"InstanceId": "i-test"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                vm.save_state(path, {})

    def apply_inputs(self, directory):
        root = Path(directory)
        args = SimpleNamespace(prefix="test-remote", scenario="remote-gateway",
            public_key=root / "test.pub", subnet_id="subnet-test", volume_gib=50,
            state_file=root / "state.json")
        proposal = {"VpcId": "vpc-test", "Ingress": vm.ingress(args.scenario, "192.0.2.1/32"),
            "ImageId": "ami-test", "InstanceType": "m7i.2xlarge", "RootDeviceName": "/dev/sda1"}
        return args, proposal, vm.Aws("eu-central-1", None, True)

    def test_bad_state_path_prevents_every_aws_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            args, proposal, aws = self.apply_inputs(directory)
            blocker = Path(directory) / "not-a-directory"
            blocker.touch()
            args.state_file = blocker / "state.json"
            with patch.object(aws, "call", return_value={}) as calls, self.assertRaises(OSError):
                vm.apply_plan(aws, args, proposal)
            calls.assert_not_called()

    def test_state_sync_failure_prevents_every_aws_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            args, proposal, aws = self.apply_inputs(directory)
            with patch.object(vm.os, "fsync", side_effect=OSError("disk failure")), \
                    patch.object(aws, "call", return_value={}) as calls, self.assertRaises(OSError):
                vm.apply_plan(aws, args, proposal)
            calls.assert_not_called()

    def test_apply_journals_before_launch_and_deletes_attached_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            args, proposal, aws = self.apply_inputs(directory)
            args.volume_gib = 300
            proposal["InstanceType"] = "g6.4xlarge"
            operations = []
            def respond(service, action, **options):
                operations.append(action)
                state = json.loads(args.state_file.read_text())
                self.assertEqual(args.state_file.stat().st_mode & 0o777, 0o600)
                self.assertTrue(state["ClientToken"])
                if action == "create-security-group":
                    return {"GroupId": "sg-test"}
                self.assertEqual(state["SecurityGroupId"], "sg-test")
                if action == "run-instances":
                    self.assertEqual(state["ApplyStatus"], "launch-requested")
                    self.assertEqual(state["KeyPairName"], args.prefix)
                    self.assertEqual(options["client_token"], state["ClientToken"])
                    self.assertEqual(options["count"], 1)
                    self.assertEqual(options["instance_type"], "g6.4xlarge")
                    self.assertEqual(options["block_device_mappings"][0]["Ebs"]["VolumeSize"], 300)
                    self.assertEqual(len(options["network_interfaces"]), 1)
                    self.assertTrue(options["network_interfaces"][0]["DeleteOnTermination"])
                    self.assertTrue(options["network_interfaces"][0]["AssociatePublicIpAddress"])
                    self.assertEqual(len(options["block_device_mappings"]), 1)
                    self.assertTrue(options["block_device_mappings"][0]["Ebs"]["DeleteOnTermination"])
                    return {"Instances": [{"InstanceId": "i-test"}]}
                return {}
            with patch.object(aws, "call", side_effect=respond), contextlib.redirect_stdout(io.StringIO()):
                vm.apply_plan(aws, args, proposal)
            final = json.loads(args.state_file.read_text())
            self.assertEqual(final["InstanceId"], "i-test")
            self.assertEqual(final["ApplyStatus"], "complete")
            self.assertEqual(operations, ["create-security-group", "authorize-security-group-ingress",
                                          "import-key-pair", "run-instances"])

    def test_launch_failure_keeps_recovery_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            args, proposal, aws = self.apply_inputs(directory)
            responses = [{"GroupId": "sg-test"}, {}, {}, ValueError("launch response lost")]
            with patch.object(aws, "call", side_effect=responses), \
                    contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                vm.apply_plan(aws, args, proposal)
            state = json.loads(args.state_file.read_text())
            self.assertEqual(state["SecurityGroupId"], "sg-test")
            self.assertEqual(state["KeyPairName"], args.prefix)
            self.assertEqual(state["ApplyStatus"], "launch-requested")
            self.assertTrue(state["ClientToken"])
            self.assertNotIn("InstanceId", state)

    def test_failed_journal_update_preserves_previous_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            vm.save_state(path, {"ApplyStatus": "started"})
            with patch.object(vm.os, "replace", side_effect=OSError("disk failure")), self.assertRaises(OSError):
                vm.update_state(path, {"ApplyStatus": "complete"})
            self.assertEqual(json.loads(path.read_text()), {"ApplyStatus": "started"})
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_verify_rejects_retained_network_interface_or_extra_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(account_id="123456789012", region="eu-central-1",
                                   state_file=Path(directory) / "state.json")
            state = {"AccountId": args.account_id, "Region": args.region, "Prefix": "test-remote",
                "Scenario": "remote-gateway", "InstanceId": "i-test", "ImageId": "ami-test",
                "InstanceType": "m7i.2xlarge", "Architecture": "x86_64", "SecurityGroupId": "sg-test",
                "RootDeviceName": "/dev/sda1", "VolumeGiB": 50,
                "Ingress": vm.ingress("remote-gateway", "192.0.2.1/32")}
            vm.save_state(args.state_file, state)
            owned = vm.tags(state["Prefix"], state["Scenario"])
            instance = {"InstanceId": "i-test", "ImageId": "ami-test", "InstanceType": state["InstanceType"],
                "Tags": owned, "State": {"Name": "running"}, "SecurityGroups": [{"GroupId": "sg-test"}],
                "MetadataOptions": {"HttpTokens": "required", "HttpPutResponseHopLimit": 1, "HttpEndpoint": "enabled"},
                "NetworkInterfaces": [{"Attachment": {"DeleteOnTermination": True}}],
                "BlockDeviceMappings": [{"DeviceName": "/dev/sda1", "Ebs": {
                    "VolumeId": "vol-test", "DeleteOnTermination": True}}]}
            image = {"OwnerId": vm.OWNER, "Architecture": "x86_64", "RootDeviceType": "ebs",
                "State": "available", "Name": "RHEL-9.6_HVM-test-x86_64-Hourly2-GP3",
                "RootDeviceName": "/dev/sda1", "BlockDeviceMappings": [{"DeviceName": "/dev/sda1", "Ebs": {}}]}
            aws = vm.Aws(args.region, None, False)
            responses = [{"Account": args.account_id, "Arn": "arn:aws:iam::123456789012:user/test"},
                {"Reservations": [{"Instances": [instance]}]}, {"Images": [image]},
                {"SecurityGroups": [{"Tags": owned, "IpPermissions": state["Ingress"]}]},
                {"Volumes": [{"Encrypted": True, "Size": 50}]}]
            with patch.object(aws, "call", side_effect=responses) as calls, contextlib.redirect_stdout(io.StringIO()):
                vm.verify(aws, args)
                self.assertTrue(all(call.args[1] in vm.READS for call in calls.call_args_list))
            # Public SSH must remain verifiable without accepting public HTTPS drift.
            state["SshAccess"] = "public"
            state["Ingress"] = vm.ingress("remote-gateway", "192.0.2.1/32", ssh_access="public")
            vm.update_state(args.state_file, state)
            group = responses[3]["SecurityGroups"][0]
            group["IpPermissions"] = copy.deepcopy(state["Ingress"])
            with patch.object(aws, "call", side_effect=responses), contextlib.redirect_stdout(io.StringIO()):
                vm.verify(aws, args)
            group["IpPermissions"][1]["IpRanges"] = [{"CidrIp": "0.0.0.0/0"}]
            with patch.object(aws, "call", side_effect=responses), self.assertRaisesRegex(ValueError, "ingress"):
                vm.verify(aws, args)
            group["IpPermissions"] = copy.deepcopy(state["Ingress"])
            instance["NetworkInterfaces"][0]["Attachment"]["DeleteOnTermination"] = False
            with patch.object(aws, "call", side_effect=responses), self.assertRaisesRegex(ValueError, "network interface"):
                vm.verify(aws, args)
            instance["NetworkInterfaces"][0]["Attachment"]["DeleteOnTermination"] = True
            instance["BlockDeviceMappings"].append({"DeviceName": "/dev/sdb"})
            with patch.object(aws, "call", side_effect=responses), self.assertRaisesRegex(ValueError, "extra disks"):
                vm.verify(aws, args)


if __name__ == "__main__":
    unittest.main()
