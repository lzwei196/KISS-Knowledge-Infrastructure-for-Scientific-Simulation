import csv, math
sim=[]
with open("marrmot_timeseries.csv") as f:
    for d in csv.DictReader(f): sim.append(float(d["Ea_mm_d"]))
obs=[]
with open("obs_et.csv") as f:
    for d in csv.DictReader(f): obs.append(float(d["ET_mm_d"]))
assert len(sim)==len(obs), (len(sim),len(obs))
W=365  # warmup
s=sim[W:]; o=obs[W:]
n=len(s)
mo=sum(o)/n; ms=sum(s)/n
sse=sum((a-b)**2 for a,b in zip(s,o))
sst=sum((b-mo)**2 for b in o)
nse=1-sse/sst
# r
cov=sum((a-ms)*(b-mo) for a,b in zip(s,o))
sds=math.sqrt(sum((a-ms)**2 for a in s)); sdo=math.sqrt(sum((b-mo)**2 for b in o))
r=cov/(sds*sdo)
alpha=(sds/math.sqrt(n))/(sdo/math.sqrt(n))
beta=ms/mo
kge=1-math.sqrt((r-1)**2+(alpha-1)**2+(beta-1)**2)
pbias=100*sum(a-b for a,b in zip(s,o))/sum(o)
print(f"n={n} (warmup {W})")
print(f"sim Ea mean {ms:.3f}  obs ET mean {mo:.3f} mm/d")
print(f"NSE  {nse:.4f}")
print(f"KGE  {kge:.4f} (r={r:.3f} alpha={alpha:.3f} beta={beta:.3f})")
print(f"r    {r:.4f}")
print(f"PBIAS {pbias:.2f}%")
