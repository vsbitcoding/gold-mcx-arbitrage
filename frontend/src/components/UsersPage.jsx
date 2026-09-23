import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { useConfirm } from "./ConfirmDialog.jsx";
import { useToast } from "./Toast.jsx";

// Manage Users (client, 03-Sep-2026): the admin creates logins, ticks the
// pages each may open, edits them later, switches them off or deletes them.
// The server enforces the same list on every API call (security.PAGE_PREFIXES),
// so an untick is a real wall, not a hidden tab.

const ROLE_LABEL = { admin: "Admin", user: "User", trader: "Trader" };
const ROLE_HINT = {
  admin: "Every page, plus Manage Users.",
  user: "Only the pages ticked below.",
  trader: "Auto Trades page only (webhook client).",
};

function when(iso) {
  if (!iso) return "never";
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function UserForm({ initial, pages, me, onClose, onSaved }) {
  const toast = useToast();
  const editing = !!initial;
  const [username, setUsername] = useState(initial?.username || "");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [role, setRole] = useState(initial?.role || "user");
  const [picked, setPicked] = useState(() => new Set(initial?.role === "user" ? initial.pages : []));
  const [active, setActive] = useState(initial ? initial.active : true);
  const [busy, setBusy] = useState(false);
  const isSelf = editing && initial.username === me;

  const allOn = picked.size === pages.length;
  function toggle(k) {
    setPicked((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  }
  function toggleAll() { setPicked(allOn ? new Set() : new Set(pages.map((p) => p.key))); }

  async function save(e) {
    e.preventDefault();
    if (busy) return;
    if (!editing && !password) { toast.error("Password is required."); return; }
    if (role === "user" && picked.size === 0) { toast.error("Tick at least one page."); return; }
    setBusy(true);
    try {
      const body = { role, active,
        pages: role === "user" ? pages.map((p) => p.key).filter((k) => picked.has(k)) : [] };
      // The name goes only when it is new or actually changed: existing logins
      // such as "Dharmesh" keep their capitals; new ones are lower-cased.
      if (!editing || username.trim() !== initial.username) body.username = username.trim().toLowerCase();
      if (password) body.password = password;
      const saved = await api.userSave(body, initial?.id);
      toast.success(editing ? `Saved ${saved.username}` : `Created ${saved.username}`);
      onSaved(saved);
    } catch (err) {
      toast.error(err.message || "Could not save");
    } finally { setBusy(false); }
  }

  return (
    <div className="pt-overlay um-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="pt-modal um-modal" role="dialog" aria-label={editing ? "Edit user" : "New user"}>
        <div className="pt-modal-head">
          <b>{editing ? `Edit ${initial.username}` : "New user"}</b>
          <button type="button" className="pt-modal-x" onClick={onClose} aria-label="Close">×</button>
        </div>
        <form className="pt-form" onSubmit={save}>
          <div className="pt-form-row">
            <label><span>Username</span>
              <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus={!editing}
                placeholder="e.g. rahul" autoComplete="off" spellCheck={false} disabled={isSelf} /></label>
            <label><span>Password{editing && <em>leave blank to keep</em>}</span>
              <div className="um-pw">
                <input type={showPw ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)}
                  placeholder={editing ? "unchanged" : "at least 6 characters"} autoComplete="new-password" />
                <button type="button" className="oh-chip um-eye" onClick={() => setShowPw((v) => !v)}
                  title={showPw ? "Hide" : "Show"}>{showPw ? "Hide" : "Show"}</button>
              </div></label>
          </div>
          <label><span>Role <em>{ROLE_HINT[role]}</em></span>
            <div className="oh-group um-roles">
              {Object.keys(ROLE_LABEL).map((r) => (
                <button key={r} type="button" className={`oh-chip ${role === r ? "on" : ""}`}
                  disabled={isSelf && r !== "admin"} onClick={() => setRole(r)}>{ROLE_LABEL[r]}</button>
              ))}
            </div></label>
          {role === "user" && (
            <div className="pt-form-syms um-pages">
              <span>Pages this user can open
                <button type="button" className="um-selall" onClick={toggleAll}>{allOn ? "Clear all" : "Select all"}</button>
              </span>
              <div className="pt-symgrid">
                {pages.map((p) => (
                  <label key={p.key} className={`pt-symtick ${picked.has(p.key) ? "on" : ""}`}>
                    <input type="checkbox" checked={picked.has(p.key)} onChange={() => toggle(p.key)} />
                    {p.label}
                  </label>
                ))}
              </div>
              <p className="pt-form-hint">{picked.size} of {pages.length} pages. The first ticked page opens after login.</p>
            </div>
          )}
          <div className="um-active">
            <span>Login</span>
            <label className={`pt-symtick ${active ? "on" : ""}`}>
              <input type="checkbox" checked={active} disabled={isSelf} onChange={(e) => setActive(e.target.checked)} />
              {active ? "Active - can sign in" : "Disabled - cannot sign in"}
            </label>
          </div>
          {isSelf && <p className="pt-form-hint">This is your own login: role and status cannot be changed here.</p>}
          <div className="pt-form-foot">
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? "Saving…" : editing ? "Save changes" : "Create user"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function UsersPage() {
  const confirm = useConfirm();
  const toast = useToast();
  const [users, setUsers] = useState(null);
  const [pages, setPages] = useState([]);
  const [err, setErr] = useState(null);
  const [form, setForm] = useState(null);          // null | {} (new) | user (edit)
  const [q, setQ] = useState("");
  const me = localStorage.getItem("arbi_user") || "";

  async function load() {
    try {
      const [u, p] = await Promise.all([api.users(), api.userPages()]);
      setUsers(u.users); setPages(p.pages); setErr(null);
    } catch (e) { setErr(e.message); }
  }
  useEffect(() => { load(); }, []);

  const labelOf = useMemo(() => Object.fromEntries(pages.map((p) => [p.key, p.label])), [pages]);
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (users || []).filter((u) => !s || u.username.includes(s) || (u.role || "").includes(s));
  }, [users, q]);

  async function remove(u) {
    const ok = await confirm({
      title: `Delete ${u.username}?`, danger: true, confirmText: "Delete",
      message: "This login stops working immediately. This cannot be undone.",
    });
    if (!ok) return;
    try { await api.userDelete(u.id); toast.success(`Deleted ${u.username}`); load(); }
    catch (e) { toast.error(e.message || "Could not delete"); }
  }
  async function toggleActive(u) {
    const ok = await confirm({
      title: u.active ? `Disable ${u.username}?` : `Enable ${u.username}?`, danger: u.active,
      confirmText: u.active ? "Disable" : "Enable",
      message: u.active ? "They will be signed out and cannot sign in until enabled again." : "They can sign in again.",
    });
    if (!ok) return;
    try {
      await api.userSave({ role: u.role, pages: u.pages, active: !u.active }, u.id);
      toast.success(`${u.username} ${u.active ? "disabled" : "enabled"}`); load();
    } catch (e) { toast.error(e.message || "Could not update"); }
  }

  return (
    <div className="um-page">
      <div className="um-head">
        <div>
          <h2>Manage Users</h2>
          <div className="um-sub">Create logins and choose which pages each one can open. Changes apply within a minute, no re-login needed.</div>
        </div>
        <div className="um-tools">
          <input className="um-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…" />
          <button type="button" className="btn btn-primary" onClick={() => setForm({})}>+ New user</button>
        </div>
      </div>

      {err && <div className="settings-banner danger">⚠ {err}</div>}
      {!users ? (
        <div className="empty-state">Loading users…</div>
      ) : shown.length === 0 ? (
        <div className="empty-state">{q ? "No user matches." : "No users yet."}</div>
      ) : (
        <div className="um-list">
          {shown.map((u) => (
            <div className={`um-row ${u.active ? "" : "off"}`} key={u.id}>
              <div className="um-id">
                <span className="user-avatar">{u.username.charAt(0).toUpperCase()}</span>
                <div>
                  <div className="um-name">{u.username}{u.username === me && <i className="um-you">you</i>}</div>
                  <div className="um-meta">
                    <span className={`um-role um-role-${u.role}`}>{ROLE_LABEL[u.role] || u.role}</span>
                    <span className={`um-state ${u.active ? "on" : ""}`}>{u.active ? "Active" : "Disabled"}</span>
                    <span>last login {when(u.last_login)}</span>
                    {u.created_by && <span>added by {u.created_by}</span>}
                  </div>
                </div>
              </div>
              <div className="um-pagechips">
                {u.role === "admin" ? (
                  <i className="um-all">All pages + Manage Users</i>
                ) : u.pages.length === 0 ? (
                  <i className="um-none">No pages</i>
                ) : u.pages.map((k) => <i key={k}>{labelOf[k] || k}</i>)}
              </div>
              <div className="um-actions">
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setForm(u)}>Edit</button>
                {u.username !== me && (
                  <>
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => toggleActive(u)}>
                      {u.active ? "Disable" : "Enable"}
                    </button>
                    <button type="button" className="btn btn-danger btn-sm" onClick={() => remove(u)}>Delete</button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {form && (
        <UserForm initial={form.id ? form : null} pages={pages} me={me}
          onClose={() => setForm(null)} onSaved={() => { setForm(null); load(); }} />
      )}
    </div>
  );
}
