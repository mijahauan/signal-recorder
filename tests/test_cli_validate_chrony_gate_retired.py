"""`hf-timestd validate` names the retired chrony refclock gate.

MEASUREMENT_MODEL.md §7.1.1 (2026-09-10) takes FUSE and HPPS out of the host
clock's electorate: both refclock lines carry `noselect`, and nothing may
re-offer them.  The gate (`core/chrony_refclock_gate.py`) did exactly that,
so it left the code on 2026-09-11.  AC0G-B4 and AC0G-ND still carry the
`[timing.authority_manager.chrony_gate]` table with `enabled = false`; the
validator must warn on the table, name the rule that retired it, and point
at the sudoers grant that went with it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from hf_timestd.cli import retired_section_issues


def _cfg(**gate):
    return {'timing': {'authority_manager': {'chrony_gate': gate}}}


class RetiredGateSectionTests(unittest.TestCase):

    def test_no_section_raises_no_issue(self):
        self.assertEqual(retired_section_issues({}), [])
        self.assertEqual(retired_section_issues({'timing': {'authority_manager': {}}}), [])

    def test_disabled_section_still_warns(self):
        issues = retired_section_issues(_cfg(enabled=False))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['severity'], 'warn')
        msg = issues[0]['message']
        self.assertIn('[timing.authority_manager.chrony_gate]', msg)
        self.assertIn('retired 2026-09-11', msg)
        self.assertIn('§7.1.1', msg)
        self.assertIn('/etc/sudoers.d/timestd-chrony-gate', msg)

    def test_enabled_section_warns_the_same_way(self):
        issues = retired_section_issues(_cfg(enabled=True, sudo=True))
        self.assertEqual(len(issues), 1)
        self.assertIn('remove the section', issues[0]['message'])


if __name__ == '__main__':
    unittest.main()


class LeftoverGateSectionIsInertTests(unittest.TestCase):
    """A deployed config that still carries the gate table must build a
    runner that never reaches for chronyc.  AC0G-ND, 2026-09-10: the gate ran
    enabled and toggled FUSE's vote twice in fourteen minutes."""

    def test_enabled_gate_table_builds_a_runner_that_never_calls_chronyc(self):
        import shutil, tempfile
        from unittest import mock
        from hf_timestd.core.authority_runner import build_authority_runner_from_config

        tmp = Path(tempfile.mkdtemp())
        try:
            cfg = {'timing': {'authority_manager': {
                'chrony_gate': {'enabled': True, 'sudo': True, 'refid': 'FUSE'}}}}
            with mock.patch('subprocess.run') as run:
                runner = build_authority_runner_from_config(
                    config=cfg,
                    fusion_status_path=tmp / 'fusion_status.json',
                    authority_output_path=tmp / 'authority.json',
                )
                runner.manager.tick()
                chronyc_calls = [c for c in run.call_args_list
                                 if any('chronyc' in str(a) for a in c.args)]
            self.assertEqual(chronyc_calls, [])
            self.assertFalse(hasattr(runner.manager, 'chrony_gate'))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
