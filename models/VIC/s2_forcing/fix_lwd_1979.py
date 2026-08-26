#!/usr/bin/env python3
"""Fix LWd_1979.nc — recompress from 71 GB back to ~16 GB with original chunking."""

import netCDF4

src = netCDF4.Dataset("KISSPATH_FORCING/LWd/LWd_1979.nc", "r")
dst = netCDF4.Dataset("KISSPATH_FORCING/LWd/LWd_1979_fixed.nc", "w")

# Copy dimensions
for d in src.dimensions:
    dst.createDimension(d, len(src.dimensions[d]))

# Copy variables with original chunking + compression
for vn, sv in src.variables.items():
    if len(sv.shape) == 3:
        dv = dst.createVariable(
            vn, sv.dtype, sv.dimensions,
            chunksizes=[1, 1800, 3600],
            zlib=True, complevel=4, shuffle=True,
        )
    else:
        dv = dst.createVariable(vn, sv.dtype, sv.dimensions)

    # Copy attributes
    for k in sv.ncattrs():
        if k != "_FillValue":
            dv.setncattr(k, sv.getncattr(k))

    # Copy data in slabs
    if len(sv.shape) == 3:
        for t in range(0, sv.shape[0], 365):
            end = min(t + 365, sv.shape[0])
            dv[t:end] = sv[t:end]
            print(f"  {vn}: timesteps {t}-{end} / {sv.shape[0]}")
    else:
        dv[:] = sv[:]

# Copy global attributes
dst.setncatts({k: src.getncattr(k) for k in src.ncattrs()})

dst.close()
src.close()
print("Done. Now run:")
print("  sudo mv KISSPATH_FORCING/LWd/LWd_1979_fixed.nc KISSPATH_FORCING/LWd/LWd_1979.nc")
