# BMI (Basic Model Interface) — References

## Specification

- **BMI Documentation**: https://bmi.readthedocs.io
- **BMI v2.0 Paper**: Hutton, E.W.H., Piper, M.D., Tucker, G.E. (2020). "The Basic Model Interface 2.0: A standard interface for coupling numerical models in the geosciences." *Journal of Open Source Software*, 5(51), 2317. DOI: 10.21105/joss.02317
- **Original Design Paper**: Peckham, S.D., Hutton, E.W.H., Norris, B. (2013). "A component-based approach to integrated modeling in the geosciences: The design of CSDMS." *Computers & Geosciences*, 53, 3-12.

## Source Code Repositories

| Repository | Language | URL |
|------------|----------|-----|
| bmipy (Python spec) | Python | https://github.com/csdms/bmi-python |
| bmi-example-python (heat model) | Python | https://github.com/csdms/bmi-example-python |
| bmi-c | C | https://github.com/csdms/bmi-c |
| bmi-cxx | C++ | https://github.com/csdms/bmi-cxx |
| bmi-fortran | Fortran | https://github.com/csdms/bmi-fortran |
| BMI specification | All | https://github.com/csdms/bmi |

## Standards

- **CSDMS Standard Names**: https://csdms.colorado.edu/wiki/CSDMS_Standard_Names
- **UDUNITS (unit conventions)**: https://www.unidata.ucar.edu/software/udunits/
- **CSDMS Home**: https://csdms.colorado.edu

## Coupling Frameworks

- **pymt (Python Modeling Toolkit)**: https://github.com/csdms/pymt — Framework for running and coupling BMI models in Python
- **Babel**: Language interoperability framework used by CSDMS for cross-language BMI coupling

## Installation

```bash
# Python specification
pip install bmipy

# Python example (heat model)
pip install bmi-example-python
# or
conda install -c conda-forge bmi-example-python
```
