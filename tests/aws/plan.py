#!/usr/bin/env python3
"""Cloud-free tests of the AWS resource plan and mutation guard."""
import importlib.machinery
import importlib.util
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
    def test_complete_plan_is_read_only_for_both_architectures(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "test.pub"
            key.write_text("ssh-ed25519 synthetic-test-key\n")
            for scenario in ["all-in-one", "remote-gateway"]:
                for arch, native in [("amd64", "x86_64"), ("arm64", "arm64")]:
                    args = SimpleNamespace(account_id="123456789012", instance_type=None, arch=arch,
                        ami_id=None, subnet_id="subnet-test", prefix="test-" + scenario, public_key=key,
                        scenario=scenario, allowed_cidr="192.0.2.1/32", region="eu-central-1", volume_gib=50,
                        state_file=Path(directory) / (scenario + arch + ".json"))
                    aws = vm.Aws(args.region, None, False)
                    responses = [
                        {"Account": args.account_id, "Arn": "arn:aws:iam::123456789012:user/test"},
                        {"InstanceTypes": [{"MemoryInfo": {"SizeInMiB": 32768},
                                            "ProcessorInfo": {"SupportedArchitectures": [native]}}]},
                        {"Images": [{"ImageId": "ami-test", "CreationDate": "2026-09-01", "OwnerId": vm.OWNER,
                            "Architecture": native, "State": "available", "RootDeviceType": "ebs",
                            "BlockDeviceMappings": [{"DeviceName": "/dev/sda1", "Ebs": {}}],
                            "RootDeviceName": "/dev/sda1", "Name": f"RHEL-9.6_HVM-test-{native}-0-Hourly2-GP3"}]},
                        {"Subnets": [{"State": "available", "VpcId": "vpc-test"}]},
                        {"RouteTables": [{"Routes": [{"DestinationCidrBlock": "0.0.0.0/0",
                                                      "GatewayId": "igw-test", "State": "active"}]}]},
                        {"Reservations": []}, {"SecurityGroups": []}, {"KeyPairs": []}]
                    with patch.object(aws, "call", side_effect=responses) as calls, \
                            patch.object(vm.subprocess, "run"):
                        proposal = vm.plan(aws, args)
                    self.assertEqual(proposal["Architecture"], native)
                    self.assertEqual(len(proposal["Ingress"]), 1 if scenario == "all-in-one" else 2)
                    self.assertTrue(all(call.args[1] in vm.READS for call in calls.call_args_list))
                    self.assertFalse(args.state_file.exists())

    def test_wrong_account_and_root_rejected(self):
        for identity in [{"Account": "000000000000", "Arn": "arn:aws:iam::000000000000:user/test"},
                         {"Account": "123456789012", "Arn": "arn:aws:iam::123456789012:root"}]:
            aws = vm.Aws("eu-central-1", None, False)
            with patch.object(aws, "call", return_value=identity), self.assertRaises(ValueError):
                vm.check_identity(aws, "123456789012")

    def test_ingress_is_explicit_and_scenario_specific(self):
        self.assertEqual([rule["FromPort"] for rule in vm.ingress("all-in-one", "192.0.2.1/32")], [22])
        self.assertEqual([rule["FromPort"] for rule in vm.ingress("remote-gateway", "192.0.2.1/32")], [22, 8443])
        for bad in ["0.0.0.0/0", "192.0.2.0/24", "::/0", "bad"]:
            with self.assertRaises(ValueError):
                vm.ingress("remote-gateway", bad)

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
            instance["NetworkInterfaces"][0]["Attachment"]["DeleteOnTermination"] = False
            with patch.object(aws, "call", side_effect=responses), self.assertRaisesRegex(ValueError, "network interface"):
                vm.verify(aws, args)
            instance["NetworkInterfaces"][0]["Attachment"]["DeleteOnTermination"] = True
            instance["BlockDeviceMappings"].append({"DeviceName": "/dev/sdb"})
            with patch.object(aws, "call", side_effect=responses), self.assertRaisesRegex(ValueError, "extra disks"):
                vm.verify(aws, args)


if __name__ == "__main__":
    unittest.main()
