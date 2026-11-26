import argparse
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cbh import cli


class ReconDomainBoundaryTests(unittest.TestCase):
    def make_scope(self, folder, inside, outside=()):
        path = Path(folder) / "scope.md"
        lines = ["## In scope"]
        lines.extend(f"- {rule}" for rule in inside)
        if outside:
            lines.append("## Out of scope")
            lines.extend(f"- {rule}" for rule in outside)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    def test_only_authorized_hosts_reach_dns_and_http(self):
        with tempfile.TemporaryDirectory() as scratch:
            scope_file = self.make_scope(
                scratch,
                ["example.test"],
                ["www.example.test"],
            )
            args = argparse.Namespace(
                target="Example.TEST.", out=str(Path(scratch) / "out"),
                scope_file=scope_file, proxy=None, burp=False,
            )
            with patch.object(cli, "configure_proxy_from_args"), redirect_stdout(io.StringIO()):
                with patch.multiple(
                    cli,
                    recon_subdomains_via_crtsh=lambda _target: {
                        "www.example.test", "api.example.test",
                        "example.test.unrelated.test", "unrelated.test",
                    },
                    recon_subdomains_via_subfinder=lambda _target: {
                        "API.Example.Test.", "notexample.test",
                        "invalid name.example.test",
                    },
                ):
                    with patch.object(cli, "recon_resolve", return_value=["192.0.2.1"]) as resolve:
                        with patch.object(cli, "recon_http_probe", return_value=None) as probe:
                            self.assertEqual(cli.cmd_recon(args), 0)

            expected = {"example.test", "api.example.test"}
            self.assertEqual({c.args[0] for c in resolve.call_args_list}, expected)
            self.assertEqual({c.args[0] for c in probe.call_args_list}, expected)
            output = Path(args.out) / "example.test" / "subdomains.txt"
            self.assertEqual(set(output.read_text().splitlines()), expected)

    def test_exact_asset_rule_does_not_authorize_parent_or_siblings(self):
        with tempfile.TemporaryDirectory() as scratch:
            scope_file = self.make_scope(scratch, ["re:^api\\.example\\.test$"])
            args = argparse.Namespace(
                target="example.test", out=str(Path(scratch) / "out"),
                scope_file=scope_file, proxy=None, burp=False,
            )
            with patch.object(cli, "configure_proxy_from_args"), redirect_stdout(io.StringIO()):
                with patch.object(
                    cli, "recon_subdomains_via_crtsh",
                    return_value={"api.example.test", "www.example.test"},
                ), patch.object(cli, "recon_subdomains_via_subfinder", return_value=set()):
                    with patch.object(cli, "recon_resolve", return_value=["192.0.2.2"]) as resolve:
                        with patch.object(cli, "recon_http_probe", return_value=None) as probe:
                            self.assertEqual(cli.cmd_recon(args), 0)

            self.assertEqual([c.args[0] for c in resolve.call_args_list], ["api.example.test"])
            self.assertEqual([c.args[0] for c in probe.call_args_list], ["api.example.test"])

    def test_missing_scope_stops_before_passive_lookup_and_output(self):
        with tempfile.TemporaryDirectory() as scratch:
            args = argparse.Namespace(
                target="example.test", out=str(Path(scratch) / "out"),
                scope_file=str(Path(scratch) / "missing.md"),
                proxy=None, burp=False,
            )
            with patch.object(cli, "recon_subdomains_via_crtsh") as lookup:
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.cmd_recon(args), 1)
            lookup.assert_not_called()
            self.assertFalse(Path(args.out).exists())

    def test_url_and_path_targets_stop_before_passive_lookup(self):
        with tempfile.TemporaryDirectory() as scratch:
            scope_file = self.make_scope(scratch, ["example.test"])
            for target in ("https://example.test/", "example.test/path", "example.test:443"):
                with self.subTest(target=target):
                    args = argparse.Namespace(
                        target=target, out=str(Path(scratch) / "out"),
                        scope_file=scope_file, proxy=None, burp=False,
                    )
                    with patch.object(cli, "recon_subdomains_via_crtsh") as lookup:
                        with redirect_stderr(io.StringIO()):
                            self.assertEqual(cli.cmd_recon(args), 1)
                    lookup.assert_not_called()
                    self.assertFalse(Path(args.out).exists())


if __name__ == "__main__":
    unittest.main()
