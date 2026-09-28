#!/usr/bin/env python3
"""Add native CLI help/version to the exact Windows-manifest TOPMODEL source pin."""
import argparse,hashlib,subprocess
from pathlib import Path
PIN='7e193d3fb3d94ffec448b04bcbe0b5d01c53bb36'
ORIGINAL='e292331e9634e2c293955175f77ead48c45fd80840dce6f54c8e608a868c6667'
MARK='/* KISS native CLI inspection: no BMI initialization or science. */'
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',nargs='?',default='.');a=p.parse_args();source=Path(a.source).resolve()
 if subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()!=PIN:raise SystemExit('Unexpected TOPMODEL source pin')
 path=source/'src/main.c';s=path.read_text()
 if MARK in s:
  if hashlib.sha256(path.read_bytes()).hexdigest()!='9622a347ffe418a7d72173d8df4a83ccd5aa2839e1b8dde94abb4438ebe76a8d':raise SystemExit('Unexpected patched main.c content')
  print('Native TOPMODEL CLI patch already applied');return
 if hashlib.sha256(path.read_bytes()).hexdigest()!=ORIGINAL:raise SystemExit('Unexpected main.c source; refusing an unreviewed patch')
 s=s.replace('#include <stdbool.h>','#include <stdbool.h>\n#include <string.h>')
 s=s.replace('int main(void)\n{', '''int main(int argc, char **argv)
{
  /* KISS native CLI inspection: no BMI initialization or science. */
  if (argc == 2 && strcmp(argv[1], "--version") == 0) {
    puts("NOAA-OWP TOPMODEL 7e193d3fb3d94ffec448b04bcbe0b5d01c53bb36");
    return 0;
  }
  if (argc > 1) {
    int help = argc == 2 && (strcmp(argv[1], "--help") == 0 || strcmp(argv[1], "-h") == 0);
    FILE *stream = help ? stdout : stderr;
    fprintf(stream, "Usage: run_bmi [--help | --version]\\n");
    fprintf(stream, "Without arguments, runs the TOPMODEL BMI driver using ./data/topmod.run.\\n");
    return help ? 0 : 2;
  }
  FILE *configuration = fopen("./data/topmod.run", "r");
  if (configuration == NULL) {
    fputs("TOPMODEL: cannot open required configuration ./data/topmod.run\\n", stderr);
    return 2;
  }
  fclose(configuration);''')
 path.write_text(s);print('Applied source-pinned native TOPMODEL CLI patch')
if __name__=='__main__':main()
