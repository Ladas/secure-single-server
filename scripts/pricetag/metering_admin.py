"""SSH-only provisioning for the pinned metering partner-user schema.

Upstream has no per-login budget administration API. Keep this database adapter
private to the host; it must be requalified when the metering pin changes.
"""
import json
import math
import os
import pwd
import re
import subprocess
import uuid


def literal(value):
    if '\0' in value or '$provision$' in value:
        raise ValueError('unsupported text in identity')
    return "'" + value.replace("'", "''") + "'"


def provision_sql(subject, name=None, budget=None, admin=False):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}', subject):
        raise ValueError('invalid subject')
    if budget is not None and (not math.isfinite(budget) or not .01 <= budget <= 10000
                               or not math.isclose(budget * 100, round(budget * 100), rel_tol=0, abs_tol=1e-8)):
        raise ValueError('monthly-usd must be 0.01–10000 with at most two decimal places')
    if admin and subject != 'admin':
        raise ValueError('bootstrap administrator must be admin')
    login = literal(subject)
    identity = literal(str(uuid.uuid5(uuid.NAMESPACE_URL, 'urn:secure-single-server:user:' + subject)))
    tags = literal(json.dumps({'first_name': name or subject}))
    statements = ["BEGIN;", "SET LOCAL standard_conforming_strings=on;",
        f"SELECT pg_advisory_xact_lock(hashtext('single-server-user'), hashtext({login}));",
        'DO $provision$ DECLARE target uuid; BEGIN',
        f'SELECT user_id INTO target FROM partner_user_logins WHERE username={login};',
        'IF target IS NULL THEN',
        f'target := {identity}::uuid;',
        'INSERT INTO partner_users(user_id,tags,created_by,updated_by) '
        f"VALUES (target,{tags}::jsonb,'ssh-admin','ssh-admin');",
        'INSERT INTO partner_user_logins(username,user_id,is_current) '
        f'VALUES ({login},target,true); END IF;',
        'IF NOT EXISTS (SELECT 1 FROM partner_users WHERE user_id=target AND active '
        'AND NOT key_revocation_pending) THEN '
        "RAISE EXCEPTION 'identity is inactive or revocation is pending'; END IF;"]
    if name is not None:
        statements.append(f"UPDATE partner_users SET tags=tags || {tags}::jsonb, "
                          "updated_by='ssh-admin', updated_at=now() WHERE user_id=target;")
    if admin:
        statements.append("UPDATE partner_users SET role='super_admin', updated_by='ssh-admin', "
                          'updated_at=now() WHERE user_id=target;')
    if budget is not None:
        statements.append('INSERT INTO quota_overrides(scope,principal,monthly_usd,updated_by) '
                          f"VALUES ('user', {login}, {budget}, 'ssh-admin') "
                          'ON CONFLICT(scope,principal) DO UPDATE SET monthly_usd=EXCLUDED.monthly_usd, '
                          "updated_by='ssh-admin',updated_at=now();")
    detail = literal(json.dumps({'monthly_usd': budget, 'bootstrap_admin': admin}))
    statements += ['INSERT INTO org_audit(actor,action,target,detail) '
                   f"VALUES ('ssh-admin','standalone.provision',{login},{detail}::jsonb);",
                   'END $provision$;', 'COMMIT;']
    return '\n'.join(statements) + '\n'


def provision(subject, name=None, budget=None, admin=False):
    if os.geteuid() != 0:
        raise ValueError('run with sudo on the gateway host')
    sql = provision_sql(subject, name, budget, admin)
    uid = pwd.getpwnam('praxis-svc').pw_uid
    subprocess.run(['sudo', '-u', 'praxis-svc', 'env', f'XDG_RUNTIME_DIR=/run/user/{uid}',
                    'podman', 'exec', '-i', 'pricetag-db', 'psql', '-X', '-q',
                    '-U', 'metering', '-d', 'metering', '-v', 'ON_ERROR_STOP=1'],
                   input=sql, text=True, check=True, cwd='/tmp', stdout=subprocess.DEVNULL)
