# Configuration Instructions for Black Box testing
In order to properly execute this suite of black box testing you must install the python packages pytRIBS and pytest,
as noted in requirements.txt. The get_benchmarks.sh script uses curl to download both the Happy Jack and Big Springs 
benchmarks stored on Zenodo into the directory benchmarks. The config.json file then must be modified to specify the 
paths to both the parallel and serial tRIBS executables, as well as the benchmark cases. 

# Running Tests
Separate tests are provided for the Big Spring and Happy Jack benchmark cases. To execute these test change to the 
big_spring or happy_jack directory and run pytest from the command line. Note you can provide additional flags to pytest 
for more details on the testing process and results.

The Happy Jack tests evaluates if:
1) Input forcing is equal to the forcing recorded by the node/pixel file.
2) That the water balance closes withing a tolerable difference between inputs, outputs, and change in storage. Currently
this test will fail if the difference is greater than 10 mm/yr.
3) The last test compares model performance using the Kling-Gupta Efficiency metric (KGE). Model estimates of snow water 
equivalent are compared to SNOTEL data. If the KGE is below 1 - 2^(1/2) (i.e. the model has the same power as the mean 
of observations) then the test will fail.

The Big Spring tests evaluate if:
1) The serial and parallel version of tRIBS produce identical outputs.
2) Evaluates the spatially and temporally averaged water balance useing the same metric as Happy Jack.
3) Uses the KGE metric compared to discharge data, currently though there are known issues with the observation data. 
Consequently this test is not currently implemented.




