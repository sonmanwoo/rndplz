"""Local account administrator CLI. Never route these operations over HTTP."""
import argparse
import json
import os
from .auth_service import AuthService, AuthError


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local invitation and account revocation administrator')
    commands = parser.add_subparsers(dest='command', required=True)
    issue = commands.add_parser('issue-invitation')
    issue.add_argument('--ttl', type=int, default=600, help='Invitation lifetime in seconds (60..3600)')
    for name in ('invitation-status', 'revoke-invitation', 'revoke-account'):
        commands.add_parser(name).add_argument('--id', required=True)
    args = parser.parse_args(argv)
    service = AuthService.from_env(os.environ)
    try:
        service._enabled()
        if args.command == 'issue-invitation':
            if not service.enrollment_enabled:
                raise AuthError('enrollment_not_enabled', 403)
            # The sole disclosure of the raw invitation; no file/log/retrieval endpoint.
            result = service.storage.issue_invitation(args.ttl)
        elif args.command == 'invitation-status':
            result = service.storage.invitation_status(args.id)
        elif args.command == 'revoke-invitation':
            service.storage.revoke_invitation(args.id)
            result = {'status': 'revoked', 'invitation_id': args.id}
        else:
            service.storage.revoke_account(args.id)
            result = {'status': 'revoked', 'account_id': args.id}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except AuthError as error:
        print(json.dumps({'status': 'failed', 'code': error.code}))
        return 1
    except Exception:
        print(json.dumps({'status': 'failed', 'code': 'account_admin_unavailable'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
