import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import { useConfirm } from "./ConfirmDialog.jsx";
import { useToast } from "./Toast.jsx";
import "./UsersPage.css";

const ROLE_LABEL = { admin: "Admin", user: "User", trader: "Trader" };
const ROLE_HINT = {
  admin: "Full access, including user management.",
  user: "Access to the pages you select below.",
  trader: "Access to Auto Trades only.",
};

function Icon({ name, size = 20, ...props }) {
  const paths = {
    users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M22 21v-2a4 4 0 0 0-3-3.87" /><circle cx="9" cy="7" r="4" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4.5 4.5" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
    shield: <><path d="m12 3 8 4v5c0 5-8 9-8 9s-8-4-8-9V7l8-4Z" /><path d="m8.5 12 2.5 2.5 4.5-5" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    pause: <><path d="M9 8v8M15 8v8" /><circle cx="12" cy="12" r="9" /></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6.1 7a7 7 0 0 1 11.55-1.65L20 8M4 16l2.35 2.65A7 7 0 0 0 17.9 17" /></>,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    edit: <><path d="m15 5 4 4M4 20l4.5-1 12-12a2.83 2.83 0 0 0-4-4l-12 12L4 20Z" /></>,
    alert: <><path d="m12 3 10 18H2L12 3ZM12 9v5M12 17h.01" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>;
}

function when(iso) {
  if (!iso) return "Never signed in";
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso) ? iso : `${iso}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return "Login time unavailable";
  return date.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function UserForm({ initial, pages, me, onClose, onSaved }) {
  const toast = useToast();
  const formId = useId();
  const dialogRef = useRef(null);
  const errorRef = useRef(null);
  const closeRef = useRef(onClose);
  const busyRef = useRef(false);
  const editing = !!initial;
  const [username, setUsername] = useState(initial?.username || "");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [role, setRole] = useState(initial?.role || "user");
  const [picked, setPicked] = useState(() => new Set(initial?.role === "user" ? initial.pages : []));
  const [pageQuery, setPageQuery] = useState("");
  const [active, setActive] = useState(initial ? initial.active : true);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const isSelf = editing && initial.username === me;
  closeRef.current = onClose;
  busyRef.current = busy;

  useEffect(() => {
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialogRef.current?.querySelector("input:not(:disabled)")?.focus();
    function onKeyDown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!busyRef.current) closeRef.current();
      }
      if (event.key !== "Tab") return;
      const focusable = [...(dialogRef.current?.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]') || [])]
        .filter((element) => element.getClientRects().length > 0);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first) { event.preventDefault(); dialogRef.current?.focus(); return; }
      if (event.shiftKey && (document.activeElement === first || !dialogRef.current?.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !dialogRef.current?.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, []);

  useEffect(() => { if (formError) errorRef.current?.focus(); }, [formError]);

  const selectedCount = pages.filter((page) => picked.has(page.key)).length;
  const allOn = pages.length > 0 && selectedCount === pages.length;
  const visiblePages = pages.filter((page) => page.label.toLowerCase().includes(pageQuery.trim().toLowerCase()));

  function toggle(key) {
    setPicked((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

  async function save(event) {
    event.preventDefault();
    if (busyRef.current) return;
    setFormError("");
    const changedName = !editing || username.trim() !== initial.username;
    if (changedName && !/^[a-z0-9][a-z0-9_.-]{2,31}$/i.test(username.trim())) {
      setFormError("Use 3–32 characters for the username. Start with a letter or number; dots, underscores and hyphens are also allowed.");
      return;
    }
    if (!editing && !password) { setFormError("Enter a password for this user."); return; }
    if (role === "user" && selectedCount === 0) { setFormError("Select at least one page this user can open."); return; }
    busyRef.current = true;
    setBusy(true);
    try {
      const body = { role, active, pages: role === "user" ? pages.map((page) => page.key).filter((key) => picked.has(key)) : [] };
      // Preserve the spelling of existing logins unless their name is changed.
      if (changedName) body.username = username.trim().toLowerCase();
      if (password) body.password = password;
      const saved = await api.userSave(body, initial?.id);
      toast.success(editing ? `Saved ${saved.username}` : `Created ${saved.username}`);
      onSaved(saved);
    } catch (error) {
      setFormError(error.message || "We couldn't save this user. Please try again.");
    } finally { busyRef.current = false; setBusy(false); }
  }

  return (
    <div className="um-dialog-overlay" onClick={(event) => { if (event.target === event.currentTarget && !busyRef.current) onClose(); }}>
      <div className="um-dialog" ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={`${formId}-title`} aria-describedby={`${formId}-description`} tabIndex={-1}>
        <div className="um-dialog-head">
          <div className="um-dialog-heading">
            <span className="um-heading-icon"><Icon name={editing ? "edit" : "users"} /></span>
            <div><h2 id={`${formId}-title`}>{editing ? "Edit user" : "Add a new user"}</h2>
              <p id={`${formId}-description`}>{editing ? `Manage login and access for ${initial.username}.` : "Set up a login and choose their workspace access."}</p>
            </div>
          </div>
          <button type="button" className="um-icon-button" onClick={onClose} disabled={busy} aria-label="Close user form"><Icon name="close" /></button>
        </div>
        <form className="um-user-form" onSubmit={save} aria-busy={busy}>
          {formError && <div className="um-form-error" role="alert" tabIndex={-1} ref={errorRef}><Icon name="alert" size={18} /><span>{formError}</span></div>}
          <fieldset className="um-form-fields" disabled={busy}>
            <div className="um-form-section">
              <h3>Login details</h3>
              <div className="um-field-row">
                <label className="um-field" htmlFor={`${formId}-username`}><span id={`${formId}-username-label`}>Username</span>
                  <input id={`${formId}-username`} value={username} onChange={(event) => setUsername(event.target.value)} required placeholder="e.g. rahul" autoComplete="off" autoCapitalize="none" spellCheck={false} disabled={isSelf} aria-labelledby={`${formId}-username-label`} aria-describedby={`${formId}-username-hint`} />
                  <small id={`${formId}-username-hint`}>{isSelf ? "Your own username cannot be changed here." : "3–32 letters, numbers, dots, underscores or hyphens."}</small>
                </label>
                <div className="um-field">
                  <label htmlFor={`${formId}-password`}>{editing ? "New password" : "Password"}{editing && <span className="um-optional" aria-hidden="true">Optional</span>}</label>
                  <div className="um-password-input">
                    <input id={`${formId}-password`} type={showPw ? "text" : "password"} value={password} onChange={(event) => setPassword(event.target.value)} required={!editing} minLength={6} placeholder={editing ? "Keep current password" : "At least 6 characters"} autoComplete="new-password" aria-describedby={`${formId}-password-hint`} />
                    <button type="button" onClick={() => setShowPw((value) => !value)} aria-label={showPw ? "Hide password" : "Show password"} aria-pressed={showPw}>{showPw ? "Hide" : "Show"}</button>
                  </div>
                  <small id={`${formId}-password-hint`}>{editing ? "Leave blank to keep the current password." : "Share these login details with the user."}</small>
                </div>
              </div>
            </div>
            <fieldset className="um-role-fieldset">
              <legend>User role</legend>
              <div className="um-role-options">
                {Object.keys(ROLE_LABEL).map((value) => (
                  <label key={value} className={`um-role-option ${role === value ? "is-selected" : ""} ${isSelf && value !== "admin" ? "is-unavailable" : ""}`}>
                    <input type="radio" name={`${formId}-role`} value={value} checked={role === value} disabled={isSelf && value !== "admin"} onChange={() => setRole(value)} />
                    <span><strong>{ROLE_LABEL[value]}</strong><small>{ROLE_HINT[value]}</small></span>
                  </label>
                ))}
              </div>
            </fieldset>
            {role === "user" && (
              <section className="um-permissions" aria-labelledby={`${formId}-pages-title`}>
                <div className="um-section-heading"><h3 id={`${formId}-pages-title`}>Page access <span>{selectedCount} / {pages.length}</span></h3>
                  <button type="button" className="um-text-button" onClick={() => setPicked(allOn ? new Set() : new Set(pages.map((page) => page.key)))}>{allOn ? "Clear all" : "Select all"}</button>
                </div>
                <label className="um-permission-search"><Icon name="search" size={17} /><input value={pageQuery} onChange={(event) => setPageQuery(event.target.value)} placeholder="Find a page…" aria-label="Search available pages" /></label>
                <div className="um-permission-grid">
                  {visiblePages.map((page) => (
                    <label key={page.key} className={`um-permission ${picked.has(page.key) ? "is-selected" : ""}`}>
                      <input type="checkbox" checked={picked.has(page.key)} onChange={() => toggle(page.key)} /><span>{page.label}</span>
                    </label>
                  ))}
                  {visiblePages.length === 0 && <p className="um-permission-empty">No pages match “{pageQuery}”.</p>}
                </div>
                <p className="um-field-hint">Select at least one page. The first selected page in this list opens after sign-in.</p>
              </section>
            )}
            <div className="um-login-status">
              <div><h3>Allow sign-in</h3><p>{active ? "This user can sign in to the workspace." : "This user cannot sign in until enabled."}</p></div>
              <label className="um-switch"><input type="checkbox" checked={active} disabled={isSelf} onChange={(event) => setActive(event.target.checked)} aria-label="Allow this user to sign in" /><span aria-hidden="true" /></label>
            </div>
            {isSelf && <p className="um-self-note"><Icon name="shield" size={16} />You’re editing your own account. Your admin role and sign-in status are protected.</p>}
          </fieldset>
          <div className="um-form-footer"><button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>Cancel</button><button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Saving changes…" : editing ? "Save changes" : "Create user"}</button></div>
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
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState(null);
  const [q, setQ] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [pending, setPending] = useState(null);
  const [expanded, setExpanded] = useState(() => new Set());
  const requestId = useRef(0);
  const mutationRef = useRef(false);
  const me = localStorage.getItem("arbi_user") || "";

  const load = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    try {
      const [userData, pageData] = await Promise.all([api.users(), api.userPages()]);
      if (id !== requestId.current) return;
      setUsers(userData.users); setPages(pageData.pages); setErr(null);
    } catch (error) {
      if (id === requestId.current) setErr(error.message || "We couldn't load your users. Please try again.");
    } finally { if (id === requestId.current) setLoading(false); }
  }, []);

  useEffect(() => { load(); return () => { requestId.current += 1; }; }, [load]);

  const labelOf = useMemo(() => Object.fromEntries(pages.map((page) => [page.key, page.label])), [pages]);
  const stats = useMemo(() => ({
    total: users?.length || 0,
    active: (users || []).filter((user) => user.active).length,
    disabled: (users || []).filter((user) => !user.active).length,
    admins: (users || []).filter((user) => user.role === "admin").length,
  }), [users]);
  const shown = useMemo(() => {
    const search = q.trim().toLowerCase();
    return (users || []).filter((user) => {
      const matchesSearch = !search || [user.username, user.role, ...(user.pages || []).map((key) => labelOf[key] || key)].some((value) => String(value || "").toLowerCase().includes(search));
      return matchesSearch && (roleFilter === "all" || user.role === roleFilter) && (statusFilter === "all" || user.active === (statusFilter === "active"));
    });
  }, [users, q, roleFilter, statusFilter, labelOf]);
  const filtered = q.trim() || roleFilter !== "all" || statusFilter !== "all";

  function resetFilters() { setQ(""); setRoleFilter("all"); setStatusFilter("all"); }

  async function changeUser(user, action) {
    if (mutationRef.current) return;
    mutationRef.current = true;
    setPending({ id: user.id, action: "confirm" });
    try {
      const deleting = action === "delete";
      const ok = await confirm({
        title: deleting ? `Delete ${user.username}?` : `${user.active ? "Disable" : "Enable"} ${user.username}?`,
        danger: deleting || user.active,
        confirmText: deleting ? "Delete user" : user.active ? "Disable login" : "Enable login",
        message: deleting ? "This login stops working immediately. This cannot be undone." : user.active ? "They will be signed out and cannot sign in until enabled again." : "They can sign in again with their existing password and page access.",
      });
      if (!ok) return;
      setPending({ id: user.id, action });
      if (deleting) {
        await api.userDelete(user.id);
        toast.success(`Deleted ${user.username}`);
      } else {
        await api.userSave({ role: user.role, pages: user.pages, active: !user.active }, user.id);
        toast.success(`${user.username} ${user.active ? "disabled" : "enabled"}`);
      }
      await load();
    } catch (error) { toast.error(error.message || "We couldn't update this user. Please try again."); }
    finally { mutationRef.current = false; setPending(null); }
  }

  return (
    <div className="um-workspace">
      <header className="um-workspace-head">
        <div><span className="um-eyebrow">Workspace administration</span><h2>Manage users</h2><p>Give your team the right access, all in one place.</p></div>
        <button type="button" className="btn btn-primary um-add-user" onClick={() => setForm({})} disabled={!users || loading || !!pending}><Icon name="plus" size={18} />Add user</button>
      </header>
      <div className="um-summary" aria-label="User overview">
        {[{ key: "total", label: "Total users", icon: "users", hint: "Across your workspace" }, { key: "active", label: "Active users", icon: "check", hint: "Allowed to sign in" }, { key: "disabled", label: "Disabled users", icon: "pause", hint: "Sign-in is paused" }, { key: "admins", label: "Administrators", icon: "shield", hint: "Full workspace access" }].map((stat) => (
          <div className={`um-summary-card um-summary-${stat.key}`} key={stat.key}><div><span className="um-stat-label">{stat.label}</span><strong>{users ? stats[stat.key] : "—"}</strong><small>{stat.hint}</small></div><span className="um-stat-icon"><Icon name={stat.icon} /></span></div>
        ))}
      </div>
      <section className="um-directory" aria-labelledby="um-directory-title">
        <div className="um-directory-heading"><div><h3 id="um-directory-title">Team directory <span>{users ? stats.total : "—"}</span></h3><p>Manage logins, roles and page permissions.</p></div><button type="button" className="um-refresh" onClick={load} disabled={loading || !!pending} aria-label="Refresh users"><Icon name="refresh" size={17} /><span>{loading && users ? "Refreshing…" : "Refresh"}</span></button></div>
        <div className="um-filterbar">
          <label className="um-directory-search"><Icon name="search" size={19} /><input value={q} onChange={(event) => setQ(event.target.value)} placeholder="Search by name, role or page…" aria-label="Search users by name, role or page" />{q && <button type="button" className="um-clear-search" onClick={() => setQ("")} aria-label="Clear user search"><Icon name="close" size={16} /></button>}</label>
          <label className="um-select-filter"><span>Role</span><select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)} aria-label="Filter users by role"><option value="all">All roles</option>{Object.entries(ROLE_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="um-select-filter"><span>Status</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label="Filter users by status"><option value="all">All statuses</option><option value="active">Active</option><option value="disabled">Disabled</option></select></label>
        </div>
        {err && <div className="um-load-error" role="alert"><Icon name="alert" size={19} /><div><strong>{users ? "Couldn't refresh users" : "Couldn't load users"}</strong><p>{err}</p>{users && <p>The last loaded users are shown below.</p>}</div><button type="button" className="btn btn-secondary" onClick={load} disabled={loading}>{loading ? "Retrying…" : "Try again"}</button></div>}
        {!users ? (
          loading ? <div className="um-directory-empty" role="status"><span className="um-loading-spinner" /><h3>Loading your team…</h3><p>Getting users and page permissions.</p></div> : <div className="um-directory-empty"><span className="um-empty-icon"><Icon name="users" size={26} /></span><h3>Your team is unavailable</h3><p>Use “Try again” above to reload your users.</p></div>
        ) : (
          <>
            <div className="um-results"><span aria-live="polite">Showing <strong>{shown.length}</strong> of {users.length} {users.length === 1 ? "user" : "users"}</span>{filtered && <button type="button" className="um-text-button" onClick={resetFilters}>Clear filters</button>}</div>
            {shown.length === 0 ? (
              <div className="um-directory-empty"><span className="um-empty-icon"><Icon name={filtered ? "search" : "users"} size={26} /></span><h3>{filtered ? "No matching users" : "Build your team"}</h3><p>{filtered ? "Try a different name, role or status to find who you’re looking for." : "Add your first user and choose the pages they can access."}</p><button type="button" className={`btn ${filtered ? "btn-secondary" : "btn-primary"}`} onClick={filtered ? resetFilters : () => setForm({})}>{filtered ? "Clear filters" : "Add your first user"}</button></div>
            ) : (
              <div className="um-directory-list" aria-busy={loading}>
                <div className="um-column-head" aria-hidden="true"><span>User</span><span>Page access</span><span>Manage</span></div>
                {shown.map((user) => {
                  const userPages = user.pages || [];
                  const isExpanded = expanded.has(user.id);
                  const busy = pending?.id === user.id;
                  return (
                    <article className={`um-person ${user.active ? "" : "is-disabled"}`} key={user.id} aria-label={`${user.username}, ${ROLE_LABEL[user.role] || user.role}, ${user.active ? "active" : "disabled"}`} aria-busy={busy && pending.action !== "confirm"}>
                      <div className="um-person-identity"><span className="um-person-avatar">{user.username.charAt(0).toUpperCase()}</span><div className="um-person-info"><div className="um-person-name">{user.username}{user.username === me && <span className="um-self-badge">You</span>}</div><div className="um-person-badges"><span className={`um-person-role ${user.role === "admin" ? "is-admin" : ""}`}>{ROLE_LABEL[user.role] || user.role}</span><span className={`um-person-status ${user.active ? "is-active" : ""}`}><i />{user.active ? "Active" : "Disabled"}</span></div><p className="um-last-login">{user.last_login ? `Last sign-in ${when(user.last_login)}` : "Never signed in"}</p></div></div>
                      <div className="um-person-access"><span className="um-mobile-label">Page access</span><div className="um-access-tags">
                        {user.role === "admin" ? <span className="um-access-all"><Icon name="shield" size={14} />All pages & user management</span> : userPages.length === 0 ? <span className="um-access-none">No pages assigned</span> : <>{(isExpanded ? userPages : userPages.slice(0, 3)).map((key) => <span key={key}>{labelOf[key] || key}</span>)}{userPages.length > 3 && <button type="button" className="um-more-pages" aria-expanded={isExpanded} aria-label={`${isExpanded ? "Show fewer" : "Show all"} pages for ${user.username}`} onClick={() => setExpanded((previous) => { const next = new Set(previous); if (next.has(user.id)) next.delete(user.id); else next.add(user.id); return next; })}>{isExpanded ? "Show less" : `+${userPages.length - 3} more`}</button>}</>}
                      </div>{user.created_by && <small>Added by {user.created_by}</small>}</div>
                      <div className="um-person-actions"><button type="button" className="btn btn-secondary um-edit-user" onClick={() => setForm(user)} disabled={!!pending || loading} aria-label={`Edit ${user.username}`}><Icon name="edit" size={15} />Edit user</button>{user.username !== me && <div className="um-secondary-actions"><button type="button" onClick={() => changeUser(user, "status")} disabled={!!pending || loading} aria-label={`${user.active ? "Disable" : "Enable"} ${user.username}`}>{busy && pending.action === "status" ? "Updating…" : user.active ? "Disable" : "Enable"}</button><span aria-hidden="true">·</span><button type="button" className="um-delete-user" onClick={() => changeUser(user, "delete")} disabled={!!pending || loading} aria-label={`Delete ${user.username}`}>{busy && pending.action === "delete" ? "Deleting…" : "Delete"}</button></div>}</div>
                    </article>
                  );
                })}
              </div>
            )}
          </>
        )}
      </section>
      <p className="um-access-note"><Icon name="shield" size={16} />Page access changes apply within a minute. Users don’t need to sign in again.</p>
      {form && <UserForm initial={form.id ? form : null} pages={pages} me={me} onClose={() => setForm(null)} onSaved={() => { setForm(null); load(); }} />}
    </div>
  );
}
