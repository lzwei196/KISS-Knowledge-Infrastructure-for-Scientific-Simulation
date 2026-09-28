a=argv(); assert(numel(a)==4);
source=canonicalize_file_name(a{1}); packages=canonicalize_file_name(a{2});
pkg('prefix',fullfile(packages,'packages'),fullfile(packages,'packages'));
pkg('local_list',fullfile(packages,'package-list'));
pkg('global_list',fullfile(packages,'global-package-list'));
wanted=strsplit(a{4},','); installed=pkg('list');
for j=1:numel(wanted)
  pair=strsplit(wanted{j},'='); assert(numel(pair)==2); found=false;
  for k=1:numel(installed)
    if strcmp(installed{k}.name,pair{1})
      assert(strcmp(installed{k}.version,pair{2}));
      ip=canonicalize_file_name(installed{k}.dir);
      assert(strncmp(ip,[packages,filesep],numel(packages)+1));
      if isfield(installed{k},'archprefix')
        ap=canonicalize_file_name(installed{k}.archprefix);
        assert(strncmp(ap,[packages,filesep],numel(packages)+1));
      end
      found=true;
    end
  end
  assert(found);
end
pkg('load','optim');
native=functions(str2func('__max_nargin_optim__'));
np=canonicalize_file_name(native.file);
assert(strncmp(np,[packages,filesep],numel(packages)+1));
assert(strcmp(np(end-3:end),'.oct'));
description=type('__max_nargin_optim__');
assert(!isempty(strfind(description{1},'dynamically-linked function')));
printf('NATIVE_OK %s\n',np);
addpath(genpath(fullfile(source,'MARRMoT','Models')));
addpath(genpath(fullfile(source,'MARRMoT','Functions')));
names=strsplit(a{3},','); assert(numel(names)==47);
for i=1:numel(names)
  name=names{i};
  mc=meta.class.fromName(name);
  assert(!isempty(mc));
  assert(strcmp(mc.Name,name));
  actual=canonicalize_file_name(which(name));
  expected=canonicalize_file_name(fullfile(source,'MARRMoT','Models','Model files',[name,'.m']));
  assert(strcmp(actual,expected));
  method_names=methods(name);
  assert(any(strcmp(method_names,'model_fun')));
  printf('CLASS_OK %s %s\n',name,actual);
end
printf('@@KISS-OCTAVE-TOOLBOX-OK@@\n');
