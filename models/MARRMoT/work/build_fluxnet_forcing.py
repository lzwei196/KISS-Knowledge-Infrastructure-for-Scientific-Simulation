import csv, math, datetime, statistics as st
SRC="KISSPATH_OBS/fluxnet/sites/CA-Oas/FULLSET_DD.csv"
LAMBDA=2.45e6; LAMBDA_MJ=2.45
GAMMA=0.0633  # kPa/C at ~530m
def delta(T):
    return 4098*(0.6108*math.exp(17.27*T/(T+237.3)))/(T+237.3)**2
rows=[]
with open(SRC) as f:
    rd=csv.DictReader(f)
    for d in rd:
        ts=d['TIMESTAMP']; dt=datetime.date(int(ts[:4]),int(ts[4:6]),int(ts[6:8]))
        Ta=float(d['TA_F']); P=float(d['P_F']); LE=float(d['LE_F_MDS'])
        Rs=float(d['SW_IN_F'])*0.0864  # W/m2 -> MJ/m2/d
        D=delta(Ta)
        # Makkink reference ET
        pet=0.61*(D/(D+GAMMA))*(Rs/LAMBDA_MJ)-0.12
        pet=max(pet,0.0)
        et_obs=LE*86400.0/LAMBDA
        rows.append((dt.isoformat(),P,pet,Ta,et_obs))
with open("forcing.csv","w") as f:
    f.write("# MARRMoT forcing FLUXNET2015 CA-Oas Old Aspen SK Canada\n")
    f.write("# P_F mm/d, Makkink Ep mm/d (from SW_IN_F), TA_F degC\n# 1996-2010 daily\n#\n")
    f.write("date,P_mm_d,Ep_mm_d,T_degC\n")
    for dt,P,pet,Ta,et in rows: f.write(f"{dt},{P:.4f},{pet:.4f},{Ta:.4f}\n")
with open("obs_et.csv","w") as f:
    f.write("date,ET_mm_d\n")
    for dt,P,pet,Ta,et in rows: f.write(f"{dt},{et:.5f}\n")
P=[r[1] for r in rows];E=[r[2] for r in rows];T=[r[3] for r in rows];ET=[r[4] for r in rows]
print(f"n={len(rows)} {rows[0][0]}..{rows[-1][0]}")
print(f"P {st.mean(P):.2f} mm/d ({sum(P)/len(rows)*365:.0f}/yr)")
print(f"Ep {st.mean(E):.2f} mm/d ({sum(E)/len(rows)*365:.0f}/yr) max {max(E):.2f}")
print(f"ET_obs {st.mean(ET):.2f} mm/d ({sum(ET)/len(rows)*365:.0f}/yr) max {max(ET):.2f}")
