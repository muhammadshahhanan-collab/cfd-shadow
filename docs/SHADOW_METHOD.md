# Campus shadow method (equations + data)

This document describes the **direct-sun geometric shadow** model used in the
CFD_Shadow dashboard time scrubber — the same class of method as ShadeMap
(ray occlusion toward the sun), not a thermal or radiative CFD shade model.

## 1. Solar position

For a given civil time at PolyU and geographic location:

- Latitude \(\varphi = 22.3045^\circ\) N  
- Longitude \(\lambda = 114.1795^\circ\) E  
- Time zone: **Hong Kong (UTC+8)**

We compute:

- Solar **altitude** \(\alpha\) (radians above horizon)  
- Solar **azimuth** \(A\) (radians; SunCalc convention: measured from **south** toward **west**)

Implementation library: **[SunCalc](https://github.com/mourner/suncalc) v2**  
(`SunCalc.getPosition(date, φ, λ)`), which evaluates the standard low-order
astronomical solar ephemeris (declination \(\delta\), hour angle \(H\), etc.).

**Units note:** SunCalc **v2.x returns altitude and azimuth in degrees**
(v1 returned radians). The viewer converts to radians before trigonometry.

Equivalent textbook relations (same physics SunCalc encodes):

\[
\sin\alpha = \sin\varphi\sin\delta + \cos\varphi\cos\delta\cos H
\]

\[
\cos A_{\mathrm{N}} = \frac{\sin\delta - \sin\varphi\sin\alpha}{\cos\varphi\cos\alpha}
\]

(with \(A_{\mathrm{N}}\) measured from north; SunCalc’s \(A\) is offset by \(\pi\) from south).

If \(\alpha \le 0\) (sun below horizon), shadow casting is disabled.

## 2. Sun direction in the viewer frame

Local CFD / viewer axes:

- \(+x\): east  
- \(+y\): up  
- \(+z\): south (Three.js \(z = -\text{north}\))

Unit vector **from a ground point toward the sun**:

\[
\begin{aligned}
\hat{s}_x &= -\sin(A)\,\cos\alpha \quad (\text{east}) \\
\hat{s}_y &= \sin\alpha \quad (\text{up}) \\
\hat{s}_{\mathrm{north}} &= -\cos(A)\,\cos\alpha
\end{aligned}
\]

(with SunCalc azimuth \(A\) from south toward west; viewer \(z=-\text{north}\)).
A directional light is placed along \(\hat{s}\) so GPU shadows fall opposite the sun.

## 3. Shadow test (geometry)

For a sample point \(P\) on the ground (or a receiving surface):

\[
P \text{ is in shade} \iff
\exists\, t>0:\quad
R(t)=P + t\,\hat{s}
\text{ intersects an occluder}
\]

Occluders = **buildings** ∪ **tree crowns**.  
Lit otherwise (direct beam only).

**GPU implementation:** Three.js `DirectionalLight` + shadow maps (depth map from
the sun’s view). This approximates the same ray–occluder test per fragment.
It is **not** diffuse-sky irradiance and **not** multiple scattering in foliage.

## 4. Time simulation

The UI sets civil time \(t\) on a chosen date. Each scrub:

1. Recompute \((\alpha, A)\) for \(t\)  
2. Update \(\hat{s}\) / light pose  
3. Re-render shadows  

Optional play mode advances \(t\) continuously (day loop).

Cumulative “hours of sun” (ShadeMap-style) would integrate the binary shade
test over discrete times; that accumulation layer is optional and not required
for the interactive scrubber.

## 5. Data used

| Input | Source | Role |
|--------|--------|------|
| Tree crowns | Segmented LAZ → `trees_solid.glb` / crowns | Soft / hard occluders (measured canopy) |
| Buildings | LandsD CSDI footprints + heights | Hard occluders |
| Ground | Flat campus plane in viewer | Shadow receiver |
| Sun ephemeris | SunCalc + PolyU lat/lon + HKT | \(\hat{s}(t)\) |
| Wind UVW | Separate CFD package | **Not** used for shadows |

## 6. Limitations (state clearly for review)

- Direct solar beam only (clear-sky geometric shade).  
- No clouds, no diffuse skylight, no thermal comfort index.  
- Crown meshes are remeshed from LiDAR (hull/voxel) + simple trunks — canopy
  transmittance is opaque (conservative shade).  
- Shadow-map resolution / bias can soften or clip thin features.

## References

- ShadeMap help: ray-from-pixel-toward-sun occlusion  
  https://shademap.app/help/  
- SunCalc: https://github.com/mourner/suncalc  
- NOAA / NREL Solar Position Algorithm (SPA) — higher-order alternative to SunCalc  
