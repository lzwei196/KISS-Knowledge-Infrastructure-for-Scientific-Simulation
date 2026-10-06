3/2002

This zip package contains two sets of input files:


1.

ex1.par        Example parameter file (simple, hypothetical configuration with
               one plane contributing laterally to a channel, with erosion and
               sediment transport)
               
ex1.pre        Example rainfall input file

To run this example, type kineros2 at the command (DOS) prompt and supply
the following responses:

     Parameter file: ex1.par
      Rainfall file: ex1.pre
        Output file: ex1.out
        Description: Example Run
     Duration (min): 200
    Time step (min): 1
       Adjust (y/n): n
     Sediment (y/n): y
  Multipliers (y/n): n


2.

wg11.par       Parameter file for Walnut Gulch subwatershed 11 with 17 elements,
               as shown on the Kineros2 home web page (runoff only - no erosion
               and sediment transport modeling)
               
4Aug80.pre     Rainfall input file with 10 spatially distributed rain gages
               (not the same storm shown on the home web page)

To run this example, supply the following responses:

     Parameter file: wg11.par
      Rainfall file: 4Aug80.pre
        Output file: 4Aug80.out
        Description: Subwatershed 11, storm of August 4, 1980
     Duration (min): 360
    Time step (min): 3
       Adjust (y/n): y
     Sediment (y/n): n
  Multipliers (y/n): y

                 Ks: 0.5
      Manning/Chezy: 1.0
                 CV: 1.0
                  G: 1.5
       Interception: 1.0


Disclaimer:

No warranties, expressed or implied, are made that this program will meet a
user's requirement for any particular application. The U.S. Department of
Agriculture disclaims all liability for direct or consequential damages
resulting from the use of this program.


Please direct all inquiries to:

Carl Unkrich

cunkrich@tucson.ars.ag.gov

520-670-6381 x178

