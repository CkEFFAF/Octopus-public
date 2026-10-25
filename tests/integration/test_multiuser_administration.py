"""Delegated user administrators cannot acquire a more privileged identity."""

from __future__ import annotations

import pytest

from tests.support.auth import TEST_PASSWORD, auth_header


@pytest.fixture
async def delegated(env):
    client, server, admin = env
    clerk = await client.post(
        "/api/users",
        headers=admin,
        json={
            "username": "clerk",
            "password": TEST_PASSWORD,
            "permissions": ["users"],
        },
    )
    assert clerk.status_code == 201, clerk.text
    target = await client.post(
        "/api/users",
        headers=admin,
        json={
            "username": "privileged",
            "password": TEST_PASSWORD,
            "permissions": ["users", "providers"],
        },
    )
    assert target.status_code == 201, target.text
    clerk_auth = await auth_header(client, username="clerk")
    admin_id = (await client.get("/api/auth/me", headers=admin)).json()["id"]
    return client, server, admin, clerk_auth, clerk.json()["id"], admin_id, target.json()["id"]


@pytest.mark.parametrize("target_kind", ["admin", "privileged"])
@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("PATCH", "", {"display_name": "changed"}),
        ("PATCH", "", {"disabled": True}),
        ("PATCH", "", {"permissions": []}),
        ("POST", "/reset-password", {"new_password": "ChangedPass12"}),
        ("POST", "/unlock-login", None),
        ("DELETE", "", None),
        ("DELETE", "/avatar", None),
    ],
)
async def test_delegated_manager_cannot_mutate_higher_account(
    delegated, target_kind, method, suffix, body
):
    client, server, admin, clerk, _, admin_id, privileged_id = delegated
    uid = admin_id if target_kind == "admin" else privileged_id
    before = server.user_manager.get_row(uid)
    response = await client.request(method, f"/api/users/{uid}{suffix}", headers=clerk, json=body)
    assert response.status_code == 403, response.text
    assert server.user_manager.get_row(uid) == before
    assert (await client.get("/api/auth/me", headers=admin)).status_code == 200


@pytest.mark.parametrize("target_kind", ["admin", "privileged"])
async def test_delegated_manager_cannot_upload_higher_account_avatar(delegated, target_kind):
    client, _, _, clerk, _, admin_id, privileged_id = delegated
    uid = admin_id if target_kind == "admin" else privileged_id
    response = await client.post(
        f"/api/users/{uid}/avatar",
        headers=clerk,
        files={"file": ("avatar.png", b"invalid image", "image/png")},
    )
    assert response.status_code == 403, response.text


@pytest.mark.parametrize(
    "action", ["enable", "disable", "delete", "set_token_quota", "set_max_agents"]
)
async def test_batch_denies_higher_accounts_and_keeps_other_results(delegated, action):
    client, server, admin, clerk, clerk_id, admin_id, privileged_id = delegated
    ordinary = await client.post(
        "/api/users",
        headers=admin,
        json={"username": "ordinary", "password": TEST_PASSWORD, "permissions": []},
    )
    assert ordinary.status_code == 201, ordinary.text
    uid = ordinary.json()["id"]
    before = [server.user_manager.get_row(i) for i in (admin_id, privileged_id)]
    response = await client.post(
        "/api/users/batch",
        headers=clerk,
        json={"user_ids": [admin_id, privileged_id, uid], "action": action},
    )
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert [(r["user_id"], r["ok"]) for r in results] == [
        (admin_id, False),
        (privileged_id, False),
        (uid, True),
    ]
    assert all(r["code"] == "FORBIDDEN" for r in results[:2])
    assert [server.user_manager.get_row(i) for i in (admin_id, privileged_id)] == before


async def test_role_assignment_checks_template_permissions_before_any_write(delegated):
    client, server, admin, clerk, _, _, target_id = delegated
    role = await client.post(
        "/api/users/roles",
        headers=admin,
        json={"user_role_name": "Provider admin", "permissions": ["users", "providers"]},
    )
    ordinary = await client.post(
        "/api/users",
        headers=admin,
        json={"username": "ordinary", "password": TEST_PASSWORD, "permissions": []},
    )
    uid = ordinary.json()["id"]
    before = server.user_manager.get_row(uid)
    response = await client.patch(
        f"/api/users/{uid}",
        headers=clerk,
        json={"role": role.json()["user_role_id"], "display_name": "must not change"},
    )
    assert response.status_code == 403, response.text
    assert server.user_manager.get_row(uid) == before


async def test_single_patch_cannot_disable_self(delegated):
    client, _, admin, clerk, clerk_id, admin_id, _ = delegated
    for auth, uid in [(admin, admin_id), (clerk, clerk_id)]:
        response = await client.patch(f"/api/users/{uid}", headers=auth, json={"disabled": True})
        assert response.status_code == 403, response.text
        assert (await client.get("/api/auth/me", headers=auth)).status_code == 200


async def test_delegated_manager_can_still_manage_ordinary_accounts(delegated):
    client, _, _, clerk, _, _, _ = delegated
    created = await client.post(
        "/api/users",
        headers=clerk,
        json={"username": "ordinary", "password": TEST_PASSWORD, "permissions": []},
    )
    assert created.status_code == 201, created.text
    uid = created.json()["id"]
    changed = await client.patch(
        f"/api/users/{uid}",
        headers=clerk,
        json={"display_name": "Test participant"},
    )
    assert changed.status_code == 200, changed.text
    reset = await client.post(
        f"/api/users/{uid}/reset-password",
        headers=clerk,
        json={"new_password": "ChangedPass12"},
    )
    assert reset.status_code == 204, reset.text
    assert (await client.delete(f"/api/users/{uid}", headers=clerk)).status_code == 204


async def test_delegated_invite_list_does_not_expose_admin_invite_codes(delegated):
    client, _, admin, clerk, _, _, _ = delegated
    privileged = await client.post(
        "/api/users/invites",
        headers=admin,
        json={"role": "admin"},
    )
    assert privileged.status_code == 201, privileged.text
    normal = await client.post(
        "/api/users/roles",
        headers=admin,
        json={"user_role_name": "Test participant", "permissions": []},
    )
    own = await client.post(
        "/api/users/invites",
        headers=clerk,
        json={"role": normal.json()["user_role_id"]},
    )
    assert own.status_code == 201, own.text
    listed = await client.get("/api/users/invites", headers=clerk)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [own.json()["id"]]
    assert privileged.json()["code"] not in listed.text
    revoked = await client.post(
        f"/api/users/invites/{privileged.json()['id']}/revoke",
        headers=clerk,
    )
    assert revoked.status_code == 403, revoked.text
    all_invites = (await client.get("/api/users/invites", headers=admin)).json()
    assert len(all_invites) == 2
    assert (
        next(row for row in all_invites if row["id"] == privileged.json()["id"])["status"]
        == "pending"
    )


async def test_invite_without_role_keeps_unprivileged_registration(delegated):
    client, _, _, clerk, _, _, _ = delegated
    response = await client.post("/api/users/invites", headers=clerk, json={})
    assert response.status_code == 201, response.text
    redeemed = await client.post(
        "/api/auth/invite/redeem",
        json={
            "code": response.json()["code"],
            "username": "participant",
            "password": TEST_PASSWORD,
        },
    )
    assert redeemed.status_code == 200, redeemed.text
    assert redeemed.json()["user"]["role"] == "user"
    assert redeemed.json()["user"]["permissions"] == []


@pytest.mark.parametrize("target_kind", ["admin", "privileged"])
@pytest.mark.parametrize("operation", ["patch", "delete", "upload_avatar", "delete_avatar"])
async def test_role_mutations_respect_target_authority(delegated, target_kind, operation):
    client, _, admin, clerk, _, _, _ = delegated
    if target_kind == "admin":
        role_id = "admin"
    else:
        created = await client.post(
            "/api/users/roles",
            headers=admin,
            json={"user_role_name": "Privileged template", "permissions": ["providers"]},
        )
        assert created.status_code == 201, created.text
        role_id = created.json()["user_role_id"]
    path = f"/api/users/roles/{role_id}"
    before = (await client.get("/api/users/roles", headers=admin)).json()
    if operation == "patch":
        response = await client.patch(path, headers=clerk, json={"description": "changed"})
    elif operation == "delete":
        response = await client.delete(path, headers=clerk)
    elif operation == "upload_avatar":
        response = await client.post(
            path + "/avatar",
            headers=clerk,
            files={"file": ("avatar.png", b"invalid image", "image/png")},
        )
    else:
        response = await client.delete(path + "/avatar", headers=clerk)
    assert response.status_code == 403, response.text
    assert (await client.get("/api/users/roles", headers=admin)).json() == before


async def test_invite_visibility_rechecks_current_role_authority(delegated):
    client, _, admin, clerk, _, _, _ = delegated
    role = await client.post(
        "/api/users/roles",
        headers=admin,
        json={"user_role_name": "Participant", "permissions": []},
    )
    role_id = role.json()["user_role_id"]
    invitation = await client.post(
        "/api/users/invites",
        headers=clerk,
        json={"role": role_id},
    )
    assert invitation.status_code == 201, invitation.text
    promoted = await client.patch(
        f"/api/users/roles/{role_id}",
        headers=admin,
        json={"permissions": ["providers"]},
    )
    assert promoted.status_code == 200, promoted.text
    listed = await client.get("/api/users/invites", headers=clerk)
    assert listed.json() == []
    assert invitation.json()["code"] not in listed.text
    response = await client.post(
        f"/api/users/invites/{invitation.json()['id']}/revoke",
        headers=clerk,
    )
    assert response.status_code == 403, response.text


async def test_creator_can_revoke_invite_for_deleted_role(delegated):
    client, _, admin, clerk, _, _, _ = delegated
    role = await client.post(
        "/api/users/roles",
        headers=admin,
        json={"user_role_name": "Temporary participant", "permissions": []},
    )
    role_id = role.json()["user_role_id"]
    invitation = await client.post(
        "/api/users/invites",
        headers=clerk,
        json={"role": role_id},
    )
    assert (await client.delete(f"/api/users/roles/{role_id}", headers=admin)).status_code == 204
    revoked = await client.post(
        f"/api/users/invites/{invitation.json()['id']}/revoke",
        headers=clerk,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"


async def test_audit_access_does_not_reveal_current_or_legacy_invite_codes(delegated):
    client, server, admin, _, _, _, _ = delegated
    auditor = await client.post(
        "/api/users",
        headers=admin,
        json={"username": "auditor", "password": TEST_PASSWORD, "permissions": ["admin_console"]},
    )
    assert auditor.status_code == 201, auditor.text
    auditor_auth = await auth_header(client, username="auditor")
    invitation = await client.post("/api/users/invites", headers=admin, json={"role": "admin"})
    code = invitation.json()["code"]
    rows = server.services.audit_repo.query(action="invite.create")
    assert rows[0].target == f"invite:{invitation.json()['id']}"
    # Old database rows used to store the bearer secret in the target column.
    for action in ("invite.create", "invite.revoke", "invite.redeem"):
        server.services.audit_repo.write(actor="admin", action=action, target=code)
    server.services.audit_repo.write(actor="admin", action="test.unrelated", target="agent:1")
    response = await client.get("/api/admin/audit-log", headers=auditor_auth)
    assert response.status_code == 200, response.text
    assert code not in response.text
    assert any(row["target"] == f"invite:{invitation.json()['id']}" for row in response.json())
    assert any(row["target"] == "agent:1" for row in response.json())
