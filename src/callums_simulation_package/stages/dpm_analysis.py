"""Simulation8.1 analysis migrated from Thomsonvalve_Sim-8-01-results-plotting2.1.py.

Helpers retain the legacy definitions of Re, St, Morsi-Alexander Cd and the
momentum-exchange diagnostic. Fluid-relative metrics use the final Eulerian
snapshot, not a reconstruction of the transient history. fp_drag is acceleration
(m/s^2); ME is a legacy diagnostic and is not the integrated Fluent DPM source.
"""
from pathlib import Path
import re
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.tri as mtri

DPI = 300
CONT_VARS = ["total-temperature", "total-pressure", "velocity-magnitude", "dynamic-pressure"]


DPM_VARS  = ["dpm-vel-mag", "dpm-diam", "dpm-concentration", "dpm-particles-in-cell"]


DPM_COLS = [
    "x", "y", "z", "u", "v", "w",
    "diameter", "t", "parcel-mass", "mass",
    "n-in-parcel", "time", "flow-time"
]


_NUM_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")


_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


_ROW_RE = re.compile(
    r"\(\(\s*(" + _FLOAT + r"(?:\s+" + _FLOAT + r"){12})\s*\)\s*([^)]+)?\)",
    re.ASCII
)


def z_from_surface_name(name: str) -> float:
    m = re.search(r"cs_z_(\d+)\s*mm", name)
    return float(m.group(1)) / 1000.0 if m else np.nan


def mkdir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def build_xy_interpolators(df_plane: pd.DataFrame):
    """
    Build LinearTriInterpolator objects for rho, uf components, velmag on an XY cross-section plane.
    Requires columns: x-coordinate, y-coordinate, density, x-velocity, y-velocity, z-velocity, velocity-magnitude
    Returns dict of interpolators or None if missing.
    """
    need = ["x-coordinate", "y-coordinate", "density", "x-velocity", "y-velocity", "z-velocity", "velocity-magnitude"]
    if any(c not in df_plane.columns for c in need):
        return None

    X = pd.to_numeric(df_plane["x-coordinate"], errors="coerce").to_numpy()
    Y = pd.to_numeric(df_plane["y-coordinate"], errors="coerce").to_numpy()
    ok = np.isfinite(X) & np.isfinite(Y)

    X = X[ok]; Y = Y[ok]
    if X.size < 50:
        return None

    tri = mtri.Triangulation(X, Y)
    analyzer = mtri.TriAnalyzer(tri)
    tri.set_mask(analyzer.get_flat_tri_mask(min_circle_ratio=0.01))

    def mk(name):
        V = pd.to_numeric(df_plane[name], errors="coerce").to_numpy()[ok]
        return mtri.LinearTriInterpolator(tri, V)

    return {
        "rho": mk("density"),
        "ux":  mk("x-velocity"),
        "uy":  mk("y-velocity"),
        "uz":  mk("z-velocity"),
        "vm":  mk("velocity-magnitude"),
    }


def compute_re_st_per_particle(
    df_dpm: pd.DataFrame,
    itp: dict,
    *,
    mu: float,
    rho_p: float,
    L_char: float,
    use_rel_for_re: bool = True,
    use_rel_for_tau_f: bool = False,
):
    """
    Adds columns to df_dpm:
      rho_f, uf_x, uf_y, uf_z, uf_mag, urel_mag, Re_p, St
    Vectorized interpolation using mtri interpolators.
    """
    xp = pd.to_numeric(df_dpm["x"], errors="coerce").to_numpy()
    yp = pd.to_numeric(df_dpm["y"], errors="coerce").to_numpy()
    dp = pd.to_numeric(df_dpm["diameter"], errors="coerce").to_numpy()

    # particle velocity
    upx = pd.to_numeric(df_dpm["u"], errors="coerce").to_numpy()
    upy = pd.to_numeric(df_dpm["v"], errors="coerce").to_numpy()
    upz = pd.to_numeric(df_dpm["w"], errors="coerce").to_numpy()

    # interpolate fluid at particle positions
    rho_f = np.asarray(np.ma.filled(itp["rho"](xp, yp), np.nan), dtype=float)
    uf_x  = np.asarray(np.ma.filled(itp["ux"](xp, yp), np.nan), dtype=float)
    uf_y  = np.asarray(np.ma.filled(itp["uy"](xp, yp), np.nan), dtype=float)
    uf_z  = np.asarray(np.ma.filled(itp["uz"](xp, yp), np.nan), dtype=float)
    uf_mag = np.sqrt(uf_x**2 + uf_y**2 + uf_z**2)

    # relative velocity
    urel_x = upx - uf_x
    urel_y = upy - uf_y
    urel_z = upz - uf_z
    urel_mag = np.sqrt(urel_x**2 + urel_y**2 + urel_z**2)

    # Reynolds number
    U_for_Re = urel_mag if use_rel_for_re else uf_mag
    Re_p = (rho_f * U_for_Re * dp) / mu

    # Stokes number
    # tau_p = rho_p d^2 / (18 mu)
    tau_p = (rho_p * dp**2) / (18.0 * mu)

    U_for_tau = urel_mag if use_rel_for_tau_f else uf_mag
    tau_f = L_char / np.maximum(U_for_tau, 1e-12)
    St = tau_p / tau_f

    # write back (keep NaN where interpolation fails)
    df_dpm["rho_f"] = rho_f
    df_dpm["uf_x"] = uf_x
    df_dpm["uf_y"] = uf_y
    df_dpm["uf_z"] = uf_z
    df_dpm["uf_mag"] = uf_mag
    df_dpm["urel_mag"] = urel_mag
    df_dpm["Re_p"] = Re_p
    df_dpm["St"] = St
    return df_dpm


def cd_morsi_alexander(Re_p: np.ndarray) -> np.ndarray:
    """
    Morsi & Alexander (1972) piecewise drag coefficient correlation.
    Input:
      Re_p : particle Reynolds number (array-like)
    Output:
      C_D  : drag coefficient (np.ndarray)

    Piecewise (as per your coefficients):
      Re < 0.1:       C_D = 24/Re
      0.1–1:          C_D = 22.73/Re + 0.0903/Re^2 + 3.69
      1–10:           C_D = 29.1667/Re - 3.8889/Re^2 + 1.222
      10–100:         C_D = 46.5/Re  - 116.67/Re^2 + 0.6167
      100–1000:       C_D = 98.33/Re - 2778/Re^2 + 0.3644
      1000–5000:      C_D = 148.62/Re - 4.75e4/Re^2 + 0.357

    Notes:
      - Handles non-finite/<=0 Re as NaN.
      - For Re > 5000, it will use the last segment (1000–5000) unless you choose otherwise.
    """
    Re = np.asarray(Re_p, dtype=float)
    Cd = np.full_like(Re, np.nan, dtype=float)

    ok = np.isfinite(Re) & (Re > 0.0)
    R = Re[ok]

    # Avoid division errors
    invR = 1.0 / R
    invR2 = invR * invR

    # masks on R (only for ok subset)
    m1 = (R < 0.1)
    m2 = (R >= 0.1) & (R < 1.0)
    m3 = (R >= 1.0) & (R < 10.0)
    m4 = (R >= 10.0) & (R < 100.0)
    m5 = (R >= 100.0) & (R < 1000.0)
    m6 = (R >= 1000.0) & (R < 5000.0)
    m7 = (R >= 5000.0)   # optional: clamp to last segment

    Cd_ok = np.empty_like(R)

    Cd_ok[m1] = 24.0 * invR[m1]
    Cd_ok[m2] = 22.73 * invR[m2] + 0.0903 * invR2[m2] + 3.69
    Cd_ok[m3] = 29.1667 * invR[m3] - 3.8889 * invR2[m3] + 1.222
    Cd_ok[m4] = 46.5 * invR[m4] - 116.67 * invR2[m4] + 0.6167
    Cd_ok[m5] = 98.33 * invR[m5] - 2778.0 * invR2[m5] + 0.3644
    Cd_ok[m6] = 148.62 * invR[m6] - 4.75e4 * invR2[m6] + 0.357

    # For Re >= 5000, keep using the last segment (common pragmatic choice)
    Cd_ok[m7] = 148.62 * invR[m7] - 4.75e4 * invR2[m7] + 0.357

    Cd[ok] = Cd_ok
    return Cd


def add_cd_and_drag_force(df_dpm: pd.DataFrame) -> pd.DataFrame:
    """
    Requires df_dpm columns:
      Re_p, rho_f, urel_mag, A_proj
    Adds:
      C_D, Fd_mag
    where:
      Fd = 0.5 * rho_f * C_D * A_proj * u_rel^2
    """
    Re = pd.to_numeric(df_dpm["Re_p"], errors="coerce").to_numpy()
    rho_f = pd.to_numeric(df_dpm["rho_f"], errors="coerce").to_numpy()
    urel = pd.to_numeric(df_dpm["urel_mag"], errors="coerce").to_numpy()
    A = pd.to_numeric(df_dpm["A_proj"], errors="coerce").to_numpy()

    Cd = cd_morsi_alexander(Re)
    Fd = 0.5 * rho_f * Cd * A * (urel ** 2)

    df_dpm["C_D"] = Cd
    df_dpm["Fd_mag"] = Fd
    return df_dpm


def add_fluent_fp_drag(df_dpm: pd.DataFrame, *, mu: float, rho_p: float) -> pd.DataFrame:
    """
    Adds Fluent-style particle drag coupling force:
      F_p-drag = ((18*mu*Cd*Re_p)/(rho_p*d_p^2*24)) * (u_p - u_f)

    Requires columns:
      - C_D
      - Re_p
      - diameter
      - u, v, w           (particle velocity)
      - uf_x, uf_y, uf_z  (fluid velocity interpolated at particle location)

    Adds columns:
      - fp_drag_x, fp_drag_y, fp_drag_z
      - fp_drag_mag
      - k_drag (the scalar prefactor)
    """
    Cd = pd.to_numeric(df_dpm["C_D"], errors="coerce").to_numpy()
    Re = pd.to_numeric(df_dpm["Re_p"], errors="coerce").to_numpy()
    dp = pd.to_numeric(df_dpm["diameter"], errors="coerce").to_numpy()

    upx = pd.to_numeric(df_dpm["u"], errors="coerce").to_numpy()
    upy = pd.to_numeric(df_dpm["v"], errors="coerce").to_numpy()
    upz = pd.to_numeric(df_dpm["w"], errors="coerce").to_numpy()

    uf_x = pd.to_numeric(df_dpm["uf_x"], errors="coerce").to_numpy()
    uf_y = pd.to_numeric(df_dpm["uf_y"], errors="coerce").to_numpy()
    uf_z = pd.to_numeric(df_dpm["uf_z"], errors="coerce").to_numpy()

    # relative velocity components (particle - fluid)
    dux = upx - uf_x
    duy = upy - uf_y
    duz = upz - uf_z

    # scalar prefactor
    # k = (18*mu*Cd*Re)/(rho_p*dp^2*24) = (3*mu*Cd*Re)/(4*rho_p*dp^2)
    k = (18.0 * mu * Cd * Re) / (rho_p * (dp ** 2) * 24.0)

    # guard against invalid dp, NaNs
    bad = ~np.isfinite(k) | ~np.isfinite(dux) | ~np.isfinite(duy) | ~np.isfinite(duz)
    k = np.where(bad, np.nan, k)

    fx = k * dux
    fy = k * duy
    fz = k * duz
    fmag = np.sqrt(fx*fx + fy*fy + fz*fz)

    df_dpm["k_drag"] = k
    df_dpm["fp_drag_x"] = fx
    df_dpm["fp_drag_y"] = fy
    df_dpm["fp_drag_z"] = fz
    df_dpm["fp_drag_mag"] = fmag
    return df_dpm


def plane_delta_t_from_flowtime(df_dpm: pd.DataFrame) -> float:
    """
    delta_t = max(flow-time) - min(flow-time) for the plane.
    """
    ft = pd.to_numeric(df_dpm["flow-time"], errors="coerce").to_numpy()
    ft = ft[np.isfinite(ft)]
    if ft.size < 2:
        return float("nan")
    return float(ft.max() - ft.min())


def momentum_exchange_plane(df_dpm: pd.DataFrame, *, mdot_p: float) -> dict:
    """
    Computes plane momentum-exchange using your definition:
      ME_mag = sum(|F_p-drag|) * mdot_p * delta_t
    Also returns vector form:
      ME_vec = (sum(Fx), sum(Fy), sum(Fz)) * mdot_p * delta_t

    Requires df_dpm columns:
      fp_drag_mag, fp_drag_x, fp_drag_y, fp_drag_z, flow-time
    """
    dt = plane_delta_t_from_flowtime(df_dpm)

    fmag = pd.to_numeric(df_dpm["fp_drag_mag"], errors="coerce").to_numpy()
    fx = pd.to_numeric(df_dpm["fp_drag_x"], errors="coerce").to_numpy()
    fy = pd.to_numeric(df_dpm["fp_drag_y"], errors="coerce").to_numpy()
    fz = pd.to_numeric(df_dpm["fp_drag_z"], errors="coerce").to_numpy()

    sum_fmag = float(np.nansum(fmag))
    sum_fx = float(np.nansum(fx))
    sum_fy = float(np.nansum(fy))
    sum_fz = float(np.nansum(fz))

    ME_mag = sum_fmag * mdot_p * dt if np.isfinite(dt) else float("nan")
    ME_x = sum_fx * mdot_p * dt if np.isfinite(dt) else float("nan")
    ME_y = sum_fy * mdot_p * dt if np.isfinite(dt) else float("nan")
    ME_z = sum_fz * mdot_p * dt if np.isfinite(dt) else float("nan")

    return {
        "delta_t_s": dt,
        "sum_Fpdrag_mag": sum_fmag,
        "sum_Fpdrag_x": sum_fx,
        "sum_Fpdrag_y": sum_fy,
        "sum_Fpdrag_z": sum_fz,
        "ME_mag": ME_mag,
        "ME_x": ME_x,
        "ME_y": ME_y,
        "ME_z": ME_z,
    }


def read_fluent_ascii_csv(path: Path) -> pd.DataFrame:
    """
    Read Fluent ASCII export CSV (export.ascii), skipping '(' header lines.
    Also collapses x-coordinate.1 style duplicates.
    """
    df = pd.read_csv(path, comment="(", skip_blank_lines=True).dropna(how="all")
    df.rename(columns=lambda c: str(c).strip().strip(chr(34)).strip("()"), inplace=True)

    # collapse duplicates like x-coordinate.1 etc
    for base in ["x-coordinate", "y-coordinate", "z-coordinate"]:
        if base not in df.columns:
            matches = [c for c in df.columns if c.startswith(base)]
            if matches:
                df[base] = df[matches[0]]
        dups = [c for c in df.columns if c.startswith(base + ".")]
        if dups:
            df.drop(columns=dups, inplace=True, errors="ignore")

    # drop nodenumber if present
    if "nodenumber" in df.columns:
        df.drop(columns=["nodenumber"], inplace=True)

    return df


def parse_surface_integral_report(path: Path) -> dict:
    """Parse Fluent surface integral report file (area_weighted_avg write_to_file)."""
    out = {}
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            name = parts[0]
            val = parts[-1]
            if name.lower() == "net":
                continue
            if _NUM_RE.match(val):
                out[name] = float(val)
    return out


def plot_profile_subplots(csv_path: Path, out_png: Path, x_col: str, y_cols: list, title: str):
    df = read_fluent_ascii_csv(csv_path)

    if x_col not in df.columns:
        raise KeyError(f"{csv_path.name}: expected x-axis column '{x_col}'. Columns: {list(df.columns)}")

    present = [c for c in y_cols if c in df.columns]
    if not present:
        print(f"⚠️ {csv_path.name}: none of requested columns found; skipping.")
        return

    x = pd.to_numeric(df[x_col], errors="coerce").to_numpy()
    order = np.argsort(x)
    x = x[order]

    n = len(present)
    ncols = 2 if n > 1 else 1
    nrows = (n + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(10, 4.5 * nrows))
    axes = np.array(axes).reshape(-1)

    for ax, col in zip(axes, present):
        y = pd.to_numeric(df[col], errors="coerce").to_numpy()[order]
        ax.plot(x, y)
        ax.set_xlabel(f"{x_col} [m]")
        ax.set_ylabel(col.replace("-", " ").title())
        ax.set_title(col.replace("-", " ").title())
        ax.grid(True, alpha=0.3)

    for ax in axes[len(present):]:
        ax.axis("off")

    fig.suptitle(title, fontsize=12)
    fig.tight_layout()
    fig.subplots_adjust(top=0.92)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=DPI)
    plt.close(fig)


def plot_axial_awa_2x2(df_ax: pd.DataFrame, out_png: Path):
    """2x2: total_energy, total_pressure (linear fit), velmag, total_temp vs z."""
    df_ax = df_ax.sort_values("z_m").reset_index(drop=True)
    x = df_ax["z_m"].to_numpy()

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    axes = axes.ravel()

    axes[0].plot(x, df_ax["total_energy_Jkg"].to_numpy(), marker="o")
    axes[0].set_title("AWA total energy vs z")
    axes[0].set_xlabel("z [m]")
    axes[0].set_ylabel("Total energy [J/kg]")
    axes[0].grid(True, alpha=0.3)

    yP = df_ax["total_pressure_Pa"].to_numpy()
    axes[1].plot(x, yP, marker="o", label="AWA total pressure")

    mask = np.isfinite(x) & np.isfinite(yP)
    if mask.sum() >= 2:
        m, b = np.polyfit(x[mask], yP[mask], 1)
        y_fit = m * x + b
        axes[1].plot(x, y_fit, linestyle="--", label=f"Fit: P = {m:.3g} z + {b:.3g}")
        yhat = m * x[mask] + b
        ss_res = np.sum((yP[mask] - yhat) ** 2)
        ss_tot = np.sum((yP[mask] - np.mean(yP[mask])) ** 2)
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
        axes[1].text(
            0.03, 0.97,
            f"dP/dz = {m:.3g} Pa/m\nIntercept = {b:.3g} Pa\nR² = {r2:.4f}",
            transform=axes[1].transAxes,
            va="top", ha="left", fontsize=9,
            bbox=dict(boxstyle="round", alpha=0.15),
        )

    axes[1].set_title("AWA total pressure vs z (linear fit)")
    axes[1].set_xlabel("z [m]")
    axes[1].set_ylabel("Total pressure [Pa]")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()

    axes[2].plot(x, df_ax["velmag_mps"].to_numpy(), marker="o")
    axes[2].set_title("AWA velocity magnitude vs z")
    axes[2].set_xlabel("z [m]")
    axes[2].set_ylabel("Velocity magnitude [m/s]")
    axes[2].grid(True, alpha=0.3)

    axes[3].plot(x, df_ax["total_temp_K"].to_numpy(), marker="o")
    axes[3].set_title("AWA total temperature vs z")
    axes[3].set_xlabel("z [m]")
    axes[3].set_ylabel("Total temperature [K]")
    axes[3].grid(True, alpha=0.3)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=DPI)
    plt.close(fig)


def hist_linear(x, title, out_png, *, bins=80, xlabel=""):
    x = pd.to_numeric(pd.Series(x), errors="coerce").to_numpy()
    x = x[np.isfinite(x)]
    if x.size == 0:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(x, bins=bins)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Count")
    ax.grid(True, alpha=0.25)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_png, dpi=DPI)
    plt.close(fig)


def heatmap_pct_xy(x_vals, y_vals, x_label, y_label, title, out_png, *, x_bins=70, y_bins=70, cmap_name="turbo"):
    # identical to your previous heatmap_pct, just here for clarity
    m = np.isfinite(x_vals) & np.isfinite(y_vals)
    x = x_vals[m]; y = y_vals[m]
    if x.size == 0:
        return
    H, x_edges, y_edges = np.histogram2d(x, y, bins=[x_bins, y_bins])
    Hpct = 100.0 * (H / np.maximum(H.sum(), 1.0))

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.pcolormesh(x_edges, y_edges, Hpct.T, shading="auto", cmap=cmap_name)
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Count [%]")
    ax.set_xlabel(x_label); ax.set_ylabel(y_label)
    ax.set_title(title)
    ax.grid(True, alpha=0.2)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_png, dpi=DPI)
    plt.close(fig)


def xy_map_mean(df_dpm, value_col, out_png, *, hose_diam_m=0.032, bins=140, min_count=2, cmap="turbo", title=None):
    """
    XY map of binned MEAN(value_col) over the hose cross-section.
    Uses the same binning grid approach as your overlay code.
    """
    R = hose_diam_m / 2.0
    x_edges = np.linspace(-R, R, bins + 1)
    y_edges = np.linspace(-R, R, bins + 1)

    grid, count = dpm_binned_grid(df_dpm, value_col, x_edges, y_edges, stat="mean", min_count=min_count)

    XX, YY = np.meshgrid(x_edges, y_edges)

    fig, ax = plt.subplots(figsize=(8.5, 6))
    pm = ax.pcolormesh(XX, YY, grid, shading="auto", cmap=cmap)
    cbar = fig.colorbar(pm, ax=ax)
    cbar.set_label(f"mean({value_col})")

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-R, R); ax.set_ylim(-R, R)
    ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]")
    ax.set_title(title or f"XY mean({value_col})")
    ax.grid(True, alpha=0.2)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_png, dpi=DPI)
    plt.close(fig)


def add_dpm_derived_columns(
    df_dpm: pd.DataFrame,
    *,
    rho_p=7850.0,
    mu=1.8e-5,
    L_char=0.032,
):
    """
    Adds:
      velmag_p, ke_p, r_p, A_proj, V_p
    (Re/St/Cd/Fd are added later if a plane interpolator is available)
    """
    u = pd.to_numeric(df_dpm["u"], errors="coerce").to_numpy()
    v = pd.to_numeric(df_dpm["v"], errors="coerce").to_numpy()
    w = pd.to_numeric(df_dpm["w"], errors="coerce").to_numpy()
    d = pd.to_numeric(df_dpm["diameter"], errors="coerce").to_numpy()

    velmag_p = np.sqrt(u*u + v*v + w*w)
    r = 0.5 * d
    A_proj = np.pi * r*r
    V_p = (4.0/3.0) * np.pi * r**3

    df_dpm["velmag_p"] = velmag_p
    df_dpm["r_p"] = r
    df_dpm["A_proj"] = A_proj
    df_dpm["V_p"] = V_p

    # KE: prefer "mass" else "parcel-mass"
    mcol = "mass" if "mass" in df_dpm.columns else "parcel-mass"
    mp = pd.to_numeric(df_dpm[mcol], errors="coerce").to_numpy()
    df_dpm["ke_p"] = 0.5 * mp * velmag_p**2

    return df_dpm


def contour_on_plane(df_plane, plane_name, field, out_png, *, hose_diam_m=0.032, levels=30, cmap="viridis"):
    if plane_name == "mid_plane":
        a_col, b_col = "y-coordinate", "z-coordinate"
        a_label, b_label = "y [m]", "z [m]"
        circle_mask = False
    else:
        a_col, b_col = "x-coordinate", "y-coordinate"
        a_label, b_label = "x [m]", "y [m]"
        circle_mask = True

    a = pd.to_numeric(df_plane[a_col], errors="coerce").to_numpy()
    b = pd.to_numeric(df_plane[b_col], errors="coerce").to_numpy()
    v = pd.to_numeric(df_plane[field], errors="coerce").to_numpy()

    ok = np.isfinite(a) & np.isfinite(b) & np.isfinite(v)
    a = a[ok]; b = b[ok]; v = v[ok]

    if a.size < 50:
        raise ValueError(f"{plane_name}: not enough points for {field}.")

    R = hose_diam_m / 2.0
    if circle_mask:
        keep = (a*a + b*b) <= (R*R) * 1.0005
        a = a[keep]; b = b[keep]; v = v[keep]
        ax_min, ax_max = -R, R
        by_min, by_max = -R, R
    else:
        ax_min, ax_max = float(np.nanmin(a)), float(np.nanmax(a))
        by_min, by_max = float(np.nanmin(b)), float(np.nanmax(b))

    tri = mtri.Triangulation(a, b)
    analyzer = mtri.TriAnalyzer(tri)
    tri.set_mask(analyzer.get_flat_tri_mask(min_circle_ratio=0.01))

    fig, ax = plt.subplots(figsize=(8.5, 6))
    cf = ax.tricontourf(tri, v, levels=levels, cmap=cmap)
    cbar = fig.colorbar(cf, ax=ax)
    cbar.set_label(field)
    ax.set_xlabel(a_label); ax.set_ylabel(b_label)
    ax.set_title(f"{plane_name}: {field}")
    ax.grid(True, alpha=0.25)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(ax_min, ax_max); ax.set_ylim(by_min, by_max)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_png, dpi=DPI)
    plt.close(fig)


def dpm_binned_grid(df_dpm, value_col, x_edges, y_edges, *, stat="sum", min_count=1):
    x = pd.to_numeric(df_dpm["x"], errors="coerce").to_numpy()
    y = pd.to_numeric(df_dpm["y"], errors="coerce").to_numpy()
    v = pd.to_numeric(df_dpm[value_col], errors="coerce").to_numpy()
    ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(v)
    x = x[ok]; y = y[ok]; v = v[ok]

    xi = np.searchsorted(x_edges, x, side="right") - 1
    yi = np.searchsorted(y_edges, y, side="right") - 1
    nx = len(x_edges) - 1
    ny = len(y_edges) - 1
    inside = (xi >= 0) & (xi < nx) & (yi >= 0) & (yi < ny)
    xi = xi[inside]; yi = yi[inside]; v = v[inside]

    count = np.zeros((ny, nx), dtype=int)
    acc = np.zeros((ny, nx), dtype=float)

    np.add.at(count, (yi, xi), 1)
    np.add.at(acc, (yi, xi), v)

    if stat == "sum":
        out = acc
    elif stat == "mean":
        out = np.where(count >= min_count, acc / np.maximum(count, 1), np.nan)
    else:
        raise ValueError("stat must be 'sum' or 'mean'")

    out = np.where(count >= min_count, out, np.nan)
    return out, count


def overlay_on_contour(
    df_plane, df_dpm, *,
    plane_name,
    bg_field,
    dpm_value_col,
    dpm_stat="sum",
    out_png: Path,
    hose_diam_m=0.032,
    bg_cmap="viridis",
    overlay_cmap="turbo",
    overlay_alpha=0.70,
    min_count=2,
    use_log_overlay=False,
    bins=140,
):
    if plane_name == "mid_plane":
        print(f"⚠️ overlay skipped for mid_plane (implemented for cs_z_* only).")
        return

    if bg_field not in df_plane.columns:
        return

    # background contours on x,y
    X = pd.to_numeric(df_plane["x-coordinate"], errors="coerce").to_numpy()
    Y = pd.to_numeric(df_plane["y-coordinate"], errors="coerce").to_numpy()
    V = pd.to_numeric(df_plane[bg_field], errors="coerce").to_numpy()
    ok = np.isfinite(X) & np.isfinite(Y) & np.isfinite(V)
    X = X[ok]; Y = Y[ok]; V = V[ok]

    R = hose_diam_m / 2.0
    keep = (X*X + Y*Y) <= (R*R) * 1.0005
    X = X[keep]; Y = Y[keep]; V = V[keep]

    tri = mtri.Triangulation(X, Y)
    analyzer = mtri.TriAnalyzer(tri)
    tri.set_mask(analyzer.get_flat_tri_mask(min_circle_ratio=0.01))

    # overlay bin edges
    x_edges = np.linspace(-R, R, bins + 1)
    y_edges = np.linspace(-R, R, bins + 1)

    grid, _count = dpm_binned_grid(df_dpm, dpm_value_col, x_edges, y_edges, stat=dpm_stat, min_count=min_count)

    # pcolormesh grid
    XX, YY = np.meshgrid(x_edges, y_edges)

    fig, ax = plt.subplots(figsize=(8.5, 6))
    cf = ax.tricontourf(tri, V, levels=30, cmap=bg_cmap)
    cbar = fig.colorbar(cf, ax=ax)
    cbar.set_label(bg_field)

    Z = grid.copy()
    if use_log_overlay:
        Z = np.log10(np.maximum(Z, 1e-30))

    pm = ax.pcolormesh(XX, YY, Z, shading="auto", cmap=overlay_cmap, alpha=overlay_alpha)
    cbar2 = fig.colorbar(pm, ax=ax)
    cbar2.set_label(f"DPM {dpm_stat}({dpm_value_col})" + (" [log10]" if use_log_overlay else ""))

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-R, R); ax.set_ylim(-R, R)
    ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]")
    ax.set_title(f"{plane_name}: {bg_field} + DPM {dpm_stat}({dpm_value_col})")

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_png, dpi=DPI)
    plt.close(fig)


def heatmap_pct(x_vals, y_vals, x_label, y_label, title, out_png, *, x_bins=60, y_bins=60, cmap_name="turbo"):
    m = np.isfinite(x_vals) & np.isfinite(y_vals)
    x = x_vals[m]; y = y_vals[m]
    if x.size == 0:
        raise ValueError("No valid samples for heatmap.")
    H, x_edges, y_edges = np.histogram2d(x, y, bins=[x_bins, y_bins])
    Hpct = 100.0 * (H / np.maximum(H.sum(), 1.0))

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.pcolormesh(x_edges, y_edges, Hpct.T, shading="auto", cmap=cmap_name)
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Count [%]")

    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title)
    ax.grid(True, alpha=0.2)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_png, dpi=DPI)
    plt.close(fig)


def make_dpm_heatmaps(df_dpm, out_dir: Path, name: str):
    v = pd.to_numeric(df_dpm["velmag_p"], errors="coerce").to_numpy()
    m = pd.to_numeric(df_dpm["mass"], errors="coerce").to_numpy() if "mass" in df_dpm.columns else pd.to_numeric(df_dpm["parcel-mass"], errors="coerce").to_numpy()
    d = pd.to_numeric(df_dpm["diameter"], errors="coerce").to_numpy()

    heatmap_pct(v, m, "Particle |V| [m/s]", "Particle mass [kg]", f"{name}: |V| vs mass (pct)", out_dir / f"{name}_vel_vs_mass_pct.png")
    heatmap_pct(v, d, "Particle |V| [m/s]", "Diameter [m]", f"{name}: |V| vs diameter (pct)", out_dir / f"{name}_vel_vs_diam_pct.png")

    # geometry metrics
    r = 0.5 * d
    A = np.pi * r*r
    SA = 4.0 * np.pi * r*r
    Vol = (4.0/3.0) * np.pi * r**3
    heatmap_pct(v, A, "Particle |V| [m/s]", "Area πr² [m²]", f"{name}: |V| vs area (pct)", out_dir / f"{name}_vel_vs_area_pct.png")
    heatmap_pct(v, SA, "Particle |V| [m/s]", "Surface area 4πr² [m²]", f"{name}: |V| vs surface area (pct)", out_dir / f"{name}_vel_vs_surface_area_pct.png")
    heatmap_pct(v, Vol, "Particle |V| [m/s]", "Volume 4/3πr³ [m³]", f"{name}: |V| vs volume (pct)", out_dir / f"{name}_vel_vs_volume_pct.png")


def cd_heatmap_vs_diameter(df_dpm: pd.DataFrame, out_png: Path):
    diam = pd.to_numeric(df_dpm["diameter"], errors="coerce").to_numpy()
    Cd   = pd.to_numeric(df_dpm["C_D"], errors="coerce").to_numpy()
    heatmap_pct_xy(
        diam, Cd,
        "Diameter [m]", "C_D",
        f"{out_png.stem}: C_D vs diameter (pct)",
        out_png,
        cmap_name="turbo"
    )


def xy_map_mean_value(df_dpm: pd.DataFrame, value_col: str, out_png: Path, *, hose_diam_m=0.032):
    xy_map_mean(
        df_dpm, value_col, out_png,
        hose_diam_m=hose_diam_m,
        cmap="turbo",
        title=f"{out_png.stem}: mean({value_col})"
    )


def xy_map_sum_value(df_dpm: pd.DataFrame, value_col: str, out_png: Path, *, hose_diam_m=0.032, bins=140, min_count=1):
    """
    XY map of binned SUM(value_col) over hose cross-section.
    """
    R = hose_diam_m / 2.0
    x_edges = np.linspace(-R, R, bins + 1)
    y_edges = np.linspace(-R, R, bins + 1)
    grid, count = dpm_binned_grid(df_dpm, value_col, x_edges, y_edges, stat="sum", min_count=min_count)
    XX, YY = np.meshgrid(x_edges, y_edges)

    fig, ax = plt.subplots(figsize=(8.5, 6))
    pm = ax.pcolormesh(XX, YY, grid, shading="auto", cmap="turbo")
    cbar = fig.colorbar(pm, ax=ax)
    cbar.set_label(f"sum({value_col})")

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-R, R); ax.set_ylim(-R, R)
    ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]")
    ax.set_title(f"{out_png.stem}: sum({value_col})")
    ax.grid(True, alpha=0.2)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_png, dpi=DPI)
    plt.close(fig)


def diameter_binned_stats(df_dpm: pd.DataFrame, out_csv: Path, *, n_bins=8):
    d = pd.to_numeric(df_dpm["diameter"], errors="coerce")
    Cd = pd.to_numeric(df_dpm["C_D"], errors="coerce")
    Fd = pd.to_numeric(df_dpm["Fd_mag"], errors="coerce")

    mask = np.isfinite(d) & np.isfinite(Cd) & np.isfinite(Fd)
    d = d[mask]; Cd = Cd[mask]; Fd = Fd[mask]

    if len(d) < 10:
        return

    edges = np.linspace(d.min(), d.max(), n_bins + 1)
    idx = np.searchsorted(edges, d, side="right") - 1
    idx = np.clip(idx, 0, n_bins - 1)

    rows = []
    for i in range(n_bins):
        sel = (idx == i)
        if sel.sum() == 0:
            continue
        rows.append({
            "d_lo": float(edges[i]),
            "d_hi": float(edges[i+1]),
            "count": int(sel.sum()),
            "Cd_mean": float(Cd[sel].mean()),
            "Cd_std":  float(Cd[sel].std(ddof=0)),
            "Cd_min":  float(Cd[sel].min()),
            "Cd_max":  float(Cd[sel].max()),
            "Fd_mean": float(Fd[sel].mean()),
            "Fd_std":  float(Fd[sel].std(ddof=0)),
            "Fd_min":  float(Fd[sel].min()),
            "Fd_max":  float(Fd[sel].max()),
        })

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_csv, index=False)



def read_fluent_dpm_text_table(path: Path) -> pd.DataFrame:
    """Read 13-column Fluent Sample rows, retaining the full injection/particle ID.

    A valid header-only file represents a station with no crossings. Malformed
    data rows fail explicitly rather than silently dropping sample records.
    """
    rows, identifiers = [], []
    has_header = False
    with path.open(encoding="utf-8", errors="strict") as stream:
        for line_number, line in enumerate(stream, 1):
            text = line.strip()
            if "parcel-mass" in text and "flow-time" in text:
                has_header = True
            if not text.startswith("(("):
                continue
            match = _ROW_RE.fullmatch(text)
            if match is None:
                raise ValueError(f"{path.name}:{line_number}: invalid DPM sample row")
            rows.append([float(value) for value in match.group(1).split()])
            identifiers.append((match.group(2) or "").strip())
    if not rows and not has_header:
        raise ValueError(f"No Fluent DPM header or sample rows in {path.name}")
    frame = pd.DataFrame(rows, columns=DPM_COLS)
    frame["particle-id"] = pd.Series(identifiers, dtype="string")
    frame["particle No."] = pd.to_numeric(
        frame["particle-id"].str.rsplit(":", n=1).str[-1], errors="coerce"
    ).astype("Int64")
    return frame


def run_dpm_analysis(config, artifacts):
    """Simulation8.1 analysis, routed through this run's configured artifact paths."""
    from ..config import ConfigError

    options = config.plotting["dpm_analysis"]
    mu = float(options["fluid_mu_Pas"])
    rho_p = float(options["particle_density_kgm3"])
    length = float(options["stokes_L_char_m"])
    hose = float(options["hose_diam_m"])
    mdot = float(options["mdot_p_kg_s"])
    if min(mu, rho_p, length, hose, mdot) <= 0:
        raise ConfigError("DPM analysis physical properties must be positive")
    global DPI
    DPI = int(options.get("dpi", 300))
    out = mkdir(artifacts.particle_plot)
    tables = mkdir(out / "tables")
    status = []
    rows = []
    combined = []
    with plt.rc_context({"savefig.dpi": DPI}):
        for path in sorted(artifacts.line_data.glob("*.csv")):
            x = "z-coordinate" if path.stem == "central-line" else "y-coordinate"
            for fields, label in ((CONT_VARS, "continuous"), (DPM_VARS, "DPM")):
                plot_profile_subplots(path, out / "line_profiles" / f"{path.stem}_{label}.png",
                                      x, fields, f"{config.run_name}: {path.stem} ({label})")

        axial = artifacts.data_export / "axial-averages.csv"
        if axial.exists():
            data = pd.read_csv(axial)
            plot_axial_awa_2x2(data, out / "axial_AWA_2x2.png")
            data.to_csv(tables / "axial_AWA.csv", index=False)

        files = sorted(artifacts.dpm_samples.glob("*.dpm"))
        if not files:
            raise FileNotFoundError(f"No .dpm samples in {artifacts.dpm_samples}")
        expected = {item["name"] for item in config.solver.get("dpm_sampling", {}).get("surfaces", [])}
        present = {path.stem for path in files}
        missing = sorted(expected - present)
        if missing:
            raise FileNotFoundError(f"Missing configured DPM sample stations: {missing}")
        for path in files:
            name = path.stem
            dpm = read_fluent_dpm_text_table(path)
            if dpm.empty:
                status.append({"station": name, "status": "no_particle_crossings", "sample_rows": 0})
                continue
            add_dpm_derived_columns(dpm, rho_p=rho_p, mu=mu, L_char=length)
            make_dpm_heatmaps(dpm, mkdir(out / "heatmaps"), name)
            for metric in ("velmag_p", "diameter", "ke_p"):
                hist_linear(dpm[metric], f"{name}: {metric}",
                            out / "histograms" / f"{name}_{metric}.png", xlabel=metric)
                xy_map_mean(dpm, metric, out / "xy_maps" / f"{name}_{metric}_mean.png",
                            hose_diam_m=hose, min_count=1, bins=int(options.get("xy_bins", 100)))
            grouped = dpm.groupby("flow-time", dropna=True).agg(
                sample_rows=("diameter", "size"), diameter_mean_m=("diameter", "mean"),
                speed_mean_mps=("velmag_p", "mean"), mass_sum_kg=("mass", "sum"))
            grouped.to_csv(tables / f"{name}_by_flow_time.csv")
            row = {"plane": name, "sample_rows": len(dpm),
                   "velmag_mean_mps": dpm["velmag_p"].mean(),
                   "diam_mean_m": dpm["diameter"].mean(), "ke_sum_J": dpm["ke_p"].sum()}
            plane_path = artifacts.contour_data / f"{name}.csv"
            itp = None
            if plane_path.exists():
                plane = read_fluent_ascii_csv(plane_path)
                for field in ("total-energy", "velocity-magnitude", "pressure"):
                    if field in plane:
                        contour_on_plane(plane, name, field, out / "plane_contours" / f"{name}_{field}.png",
                                         hose_diam_m=hose)
                itp = build_xy_interpolators(plane)
                if options.get("static_overlays", True):
                    for field, metric, stat in (("total-energy", "ke_p", "sum"),
                                                ("velocity-magnitude", "velmag_p", "mean"),
                                                ("pressure", "diameter", "mean")):
                        if field in plane:
                            overlay_on_contour(plane, dpm, plane_name=name, bg_field=field,
                                               dpm_value_col=metric, dpm_stat=stat,
                                               out_png=out / "static_overlays" / f"{name}_{metric}.png",
                                               hose_diam_m=hose, min_count=1)
            if itp is not None:
                compute_re_st_per_particle(dpm, itp, mu=mu, rho_p=rho_p, L_char=length)
                add_cd_and_drag_force(dpm)
                add_fluent_fp_drag(dpm, mu=mu, rho_p=rho_p)
                row.update(momentum_exchange_plane(dpm, mdot_p=mdot))
                row["fluid_reference"] = "final_Eulerian_snapshot"
                for metric in ("Re_p", "St", "C_D", "Fd_mag"):
                    values = pd.to_numeric(dpm[metric], errors="coerce")
                    row.update({f"{metric}_mean": values.mean(), f"{metric}_std": values.std(ddof=0),
                                f"{metric}_min": values.min(), f"{metric}_max": values.max()})
                    hist_linear(values, f"{name}: {metric}",
                                out / "histograms" / f"{name}_{metric}.png", xlabel=metric)
                    heatmap_pct_xy(dpm["diameter"].to_numpy(), values.to_numpy(), "Diameter [m]",
                                   metric, f"{name}: {metric} vs diameter",
                                   out / "diameter_heatmaps" / f"{name}_{metric}.png")
                    xy_map_mean(dpm, metric, out / "xy_maps" / f"{name}_{metric}_mean.png",
                                hose_diam_m=hose, min_count=1)
                xy_map_sum_value(dpm, "Fd_mag", out / "xy_maps" / f"{name}_Fd_sum.png", hose_diam_m=hose)
                diameter_binned_stats(dpm, tables / f"{name}_Cd_Fd_by_diameter.csv")
                combined.append(dpm[["Re_p", "St"]])
                status.append({"station": name, "status": "analysed", "sample_rows": len(dpm)})
            else:
                status.append({"station": name, "status": "particle_only_no_fluid_interpolator",
                               "sample_rows": len(dpm)})
            dpm.to_csv(tables / f"{name}_particles.csv", index=False)
            rows.append(row)
        pd.DataFrame(status).to_csv(tables / "sampling_status.csv", index=False)
        pd.DataFrame(rows).to_csv(tables / "particle_properties_by_plane.csv", index=False)
        if combined:
            all_rows = pd.concat(combined, ignore_index=True)
            for metric in ("Re_p", "St"):
                hist_linear(all_rows[metric], f"All sampled stations: {metric}",
                            out / "histograms" / f"ALL_{metric}.png", xlabel=metric)
