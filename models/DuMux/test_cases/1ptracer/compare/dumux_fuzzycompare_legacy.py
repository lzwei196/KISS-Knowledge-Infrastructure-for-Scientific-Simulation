# SPDX-FileCopyrightText: Copyright © DuMux Project contributors, see AUTHORS.md in root folder
# SPDX-License-Identifier: GPL-3.0-or-later

""" A module for fuzzy comparing VTK or CSV & other data files

This module provides methods to compare two VTK files. Applicable
for all VTK style formats like VTK files. Fuzzy compares numbers by
using absolute and/or relative difference comparison.

This module also provides methods to compare two data files.
Applicable for all style formats like e.g. csv files.
Fuzzy compares numbers by using absolute and/or relative difference comparison.
"""

import xml.etree.ElementTree as ET
from operator import attrgetter, itemgetter
import csv
import sys
import math
import os
import functools

# Note: these issues can be improved on by factoring out functions
# but we ignore it for know ("legacy code")
# pylint: disable=too-many-arguments,too-many-locals,too-many-branches,too-many-statements


def compareVTK(
    vtk1,
    vtk2,
    absolute=1.5e-7,
    relative=1e-2,
    zeroValueThreshold=None,
    ignoreFields=None,
    verbose=True,
):
    """take two vtk files and compare them. Returns an exit key as returnvalue.

    Arguments:
    ----------
    vtk1, vtk2 : string
        The filenames of the vtk files to compare. If a pvd file is given
        instead, the corresponding possibly parallel vtk file(s) have to be
        present and will be converted to a (series of) sequential vtk file(s).
        The last one in the natural ordering of these files will be taken for
        comparison.

    Keyword Arguments:
    ------------------
    absolute : float
        The epsilon used for comparing numbers with an absolute criterion
    relative: float
        The epsilon used for comparing numbers with an relative criterion
    zeroValueThreshold: dict
        A dictionary of parameter value pairs that set the threshold under
        which a number is treated as zero for a certain parameter. Use this parameter if
        you have to avoid comparisons of very small numbers for a certain parameter.
    ignoreFields: list
        A list of field names to be ignored in the comparison
    verbose : bool
        If the script should produce informative output. Enabled by default as the details
        give the tester a lot more information on why tests fail.
    """

    # construct element tree from vtk file
    with open(vtk1) as vtk1File:
        root1 = ET.fromstring(vtk1File.read())
    with open(vtk2) as vtk2File:
        root2 = ET.fromstring(vtk2File.read())

    zeroValueThreshold = zeroValueThreshold or {}

    # implement ignoring fields by setting a very high threshold
    if ignoreFields is not None:
        for field in ignoreFields:
            zeroValueThreshold[field] = 1e100

    # convert parallel vtu to sequential vtu if necessary
    convertedFromParallelVtu = False
    if vtk1.endswith(".pvtu"):
        root1 = convertPVTUToVTU(root1, vtk1)
        convertedFromParallelVtu = True
    if vtk2.endswith(".pvtu"):
        root2 = convertPVTUToVTU(root2, vtk2)
        convertedFromParallelVtu = True

    # sort the vtk file in case nodes appear in different positions
    # e.g. because of minor changes in the output code
    sortedroot1 = sortVTK(root1)
    sortedroot2 = sortVTK(root2)

    if verbose:
        print(
            f"Comparing {vtk1} and {vtk2}\n"
            f"... with a maximum relative error of {relative} and "
            f"a maximum absolute error of {absolute}*max_abs_parameter_value."
        )

    # sort the vtk file so that the comparison is independent of the
    # index numbering (coming e.g. from different grid managers)
    sortedroot1, sortedroot2 = sortVTKByCoordinates(
        sortedroot1, sortedroot2, verbose, convertedFromParallelVtu
    )

    # do the fuzzy compare
    if isFuzzyEqualNode(
        sortedroot1,
        sortedroot2,
        absolute,
        relative,
        zeroValueThreshold,
        verbose,
        convertedFromParallelVtu,
    ):
        print("Fuzzy comparison done (equal)")
        return 0

    print("Fuzzy comparison done (not equal)")
    return 1


def convertPVTUToVTU(pvturoot, filename):
    """
    Convert parallel piece *.pvtu file to sequential *.vtu file
    by glueing the pieces together removing duplicate vertices
    """

    # get the directory of the vtu file in case the piece paths are relative
    dirname = os.path.dirname(os.path.abspath(filename))
    # get the piece file names from the parallel vtu
    pieces = []
    for piece in pvturoot.findall(".//Piece"):
        piecename = os.path.join(dirname, os.path.basename(piece.attrib["Source"]))
        with open(piecename) as pieceFile:
            pieces.append(ET.fromstring(pieceFile.read()))

    root = pieces[0]
    rootCellDataArrays = []
    rootPointDataArrays = []

    for dataArray in root.findall(".//PointData/DataArray"):
        rootPointDataArrays.append(dataArray)
    for dataArray in root.findall(".//CellData/DataArray"):
        rootCellDataArrays.append(dataArray)
    for dataArray in root.findall(".//DataArray"):
        if dataArray.attrib["Name"] == "connectivity":
            rootConnectivity = dataArray
        if dataArray.attrib["Name"] == "types":
            rootTypes = dataArray
        if dataArray.attrib["Name"] == "offsets":
            rootOffsets = dataArray
        if dataArray.attrib["Name"] == "Coordinates":
            rootCoordinates = dataArray

    # add all pieces to the first piece
    for piece in pieces[1:]:
        cellDataArrays = []
        pointDataArrays = []
        for dataArray in piece.findall(".//PointData/DataArray"):
            pointDataArrays.append(dataArray)
        for dataArray in piece.findall(".//CellData/DataArray"):
            cellDataArrays.append(dataArray)
        for dataArray in piece.findall(".//DataArray"):
            if dataArray.attrib["Name"] == "connectivity":
                connectivity = dataArray
            if dataArray.attrib["Name"] == "types":
                types = dataArray
            if dataArray.attrib["Name"] == "offsets":
                offsets = dataArray
            if dataArray.attrib["Name"] == "Coordinates":
                coordinates = dataArray

        # compute offset for the offsets vector (it's the last entry of the current root piece)
        for dataArray in root.findall(".//Cells/DataArray"):
            if dataArray.attrib["Name"] == "offsets":
                offsetsOffset = int(dataArray.text.strip().rsplit(" ", 1)[1])

        # add the offsets to the root piece
        for value in offsets.text.strip().split():
            newvalue = " " + str(int(value) + offsetsOffset) + " "
            rootOffsets.text += newvalue

        # compute offset for the connectivity vector
        # (it's the number of points of the current root piece)
        rootNumPoints = int(root.findall(".//Piece")[0].attrib["NumberOfPoints"])
        rootNumCells = int(root.findall(".//Piece")[0].attrib["NumberOfCells"])

        # add the connectivity vector to the root piece
        for value in connectivity.text.strip().split():
            newvalue = " " + str(int(value) + rootNumPoints) + " "
            rootConnectivity.text += newvalue

        # add the types and coordinates
        rootTypes.text += " " + types.text
        rootCoordinates.text += " " + coordinates.text

        # add all the data arrays
        for i, dataArray in enumerate(cellDataArrays):
            rootCellDataArrays[i].text += " " + dataArray.text
        for i, dataArray in enumerate(pointDataArrays):
            rootPointDataArrays[i].text += " " + dataArray.text

        # update the number of cells and points
        newNumPoints = int(piece.findall(".//Piece")[0].attrib["NumberOfPoints"]) + rootNumPoints
        newNumCells = int(piece.findall(".//Piece")[0].attrib["NumberOfCells"]) + rootNumCells

        root.findall(".//Piece")[0].attrib["NumberOfPoints"] = str(newNumPoints)
        root.findall(".//Piece")[0].attrib["NumberOfCells"] = str(newNumCells)

    # for debugging the merged vtu file can be written out and viewed in paraview
    # sourcename = pvturoot.findall(".//Piece")[0].attrib["Source"]
    # testname = os.path.join(
    #     dirname, "comparisontemp-" + os.path.basename(vtuname)
    # )
    # vtu = ET.ElementTree(root)
    # vtu.write(testname)

    return root


# fuzzy compare of VTK nodes
def isFuzzyEqualNode(
    node1, node2, absolute, relative, zeroValueThreshold, verbose, convertedFromParallelVtu=False
):
    """Check if two XML nodes are equal (node contains attributes and text)"""
    isEqual = True
    for node1child, node2child in zip(node1.iter(), node2.iter()):
        if node1.tag != node2.tag:
            if verbose:
                print(f"The name of the node differs in: {node1.tag} and {node2.tag}")
                isEqual = False
            else:
                return False
        if not convertedFromParallelVtu and list(node1.attrib.items()) != list(
            node2.attrib.items()
        ):
            if verbose:
                print(f"Attributes differ in node: {node1.tag}")
                print("Attributes1: ", list(node1.attrib.items()))
                print("Attributes2: ", list(node2.attrib.items()))
                isEqual = False
            else:
                return False
        if len(list(node1.iter())) != len(list(node2.iter())):
            if verbose:
                print(f"Number of children differs in node: {node1.tag}")
                isEqual = False
            else:
                return False
        if node1child.text or node2child.text:
            if node1child.get("NumberOfComponents") is None:
                numberOfComponents = 1
            else:
                numberOfComponents = int(node1child.attrib["NumberOfComponents"])
            if not isFuzzyEqualText(
                node1child.text,
                node2child.text,
                node1child.attrib["Name"],
                numberOfComponents,
                absolute,
                relative,
                zeroValueThreshold,
                verbose,
            ):
                if node1child.attrib["Name"] == node2child.attrib["Name"]:
                    if verbose:
                        isEqual = False
                    else:
                        return False
                else:
                    if verbose:
                        print(
                            "Comparing different parameters: "
                            f"{node1child.attrib['Name']} and {node2child.attrib['Name']}"
                        )
                        isEqual = False
                    else:
                        return False
    return isEqual


# fuzzy compare of text (in the xml sense) consisting of whitespace separated numbers
def isFuzzyEqualText(
    text1, text2, parameter, numComp, absolute, relative, zeroValueThreshold, verbose
):
    """Check if a test of two XML nodes is equal"""
    list1 = text1.split()
    list2 = text2.split()
    # difference only in whitespace?
    if list1 == list2:
        return True
    # compare number by number
    isEqual = True

    # first split the list into compononents
    lists1 = []
    lists2 = []
    parameters = []
    for i in range(0, numComp):
        lists1.append(list1[i::numComp])
        lists2.append(list2[i::numComp])
        if numComp > 1:
            parameters.append(f"{parameter}_{i}")
            # if zero threshold was set for all components,
            # one component inherits it from the parameter
            if parameter in zeroValueThreshold:
                zeroValueThreshold[f"{parameter}_{i}"] = zeroValueThreshold[parameter]
        else:
            parameters.append(parameter)

    for list1, list2, param in zip(lists1, lists2, parameters):
        # for verbose output
        maxRelativeDifference = 0.0
        message = ""

        # see inspiration, explanations in
        # https://randomascii.wordpress.com/2012/02/25/comparing-floating-point-numbers-2012-edition/
        # get the order of magnitude of the parameter by calculating the max
        floatList1 = [float(i) for i in list1]
        floatList2 = [float(i) for i in list2]

        # check for nan and inf
        for number1, number2 in zip(floatList1, floatList2):
            if math.isnan(number1) or math.isnan(number2):
                print(f"Parameter {param} contains NaN!")
                return False
            if math.isinf(number1) or math.isinf(number2):
                print(f"Parameter {param} contains inf!")
                return False

        # Manipulate the data set for the sake of sensible comparison.
        # If the parameter is listed in the zeroThreshold dictionary,
        # replace all float under threshold with zero.
        # Only replace them with zero if the parameters in both lists are under the threshold.
        # Otherwise we compare a non-zero value with 0 later.
        if param in zeroValueThreshold:
            zeroThr = float(zeroValueThreshold[param])
            floatList1 = [
                0.0 if (abs(i) < zeroThr) and (abs(j) < zeroThr) else i
                for i, j in zip(floatList1, floatList2)
            ]
            floatList2 = [
                0.0 if (abs(i) < zeroThr) and (abs(j) < zeroThr) else j
                for i, j in zip(floatList1, floatList2)
            ]

        absFloatList1 = [abs(i) for i in floatList1]
        absFloatList2 = [abs(i) for i in floatList2]

        magnitude = max(max(absFloatList1), max(absFloatList2))
        minimal = min(min(absFloatList1), min(absFloatList2))

        for number1, number2 in zip(floatList1, floatList2):
            diff = abs(number1 - number2)
            largernumber = max(abs(number1), abs(number2))

            # If the absolute criterion is satisfied we consider the numbers equal...
            # scale the absolute tolerance with the magnitude of the parameter
            if diff <= absolute * magnitude:
                continue

            # ...if not check the relative criterion
            if diff <= largernumber * relative:
                continue

            # the numbers are not equal
            if verbose:
                isEqual = False
                if largernumber != 0.0:
                    if diff / largernumber > maxRelativeDifference:
                        maxRelativeDifference = diff / largernumber
                        message = (
                            f"Difference is too large: {maxRelativeDifference:.2%} "
                            f"-> between: {number1} and {number2}"
                        )
            else:
                return False

        if verbose and maxRelativeDifference != 0.0:
            print(
                f"\nData differs in parameter: {param}\n",
                message,
                f"Info for {param}: "
                f"max_abs_parameter_value={magnitude} and min_abs_parameter_value={minimal}.",
            )
            if param in zeroValueThreshold:
                print(
                    f"For parameter {param} a zero value threshold"
                    f" of {zeroValueThreshold[param]} was given."
                )

    return isEqual


def getNameOfNode(elem):
    """Function helper to return the name of an attribute used as sort key"""
    name = elem.get("Name")
    if name:
        try:
            return str(name)
        except ValueError:
            return ""
    return ""


# sorts attributes of an item and returns a sorted item
def sortAttributes(item, sorteditem):
    """Sort the attributes of a node"""
    attrkeys = sorted(item.keys())
    for key in attrkeys:
        sorteditem.set(key, item.get(key))


def sortElements(items, newroot):
    """Sort all elements of a node"""
    items = sorted(items, key=getNameOfNode)
    items = sorted(items, key=attrgetter("tag"))

    # Once sorted, we sort each of the items
    for item in items:
        # Create a new item to represent the sorted version
        # of the next item, and copy the tag name and contents
        newitem = ET.Element(item.tag)
        if item.text and not item.text.isspace():
            newitem.text = item.text

        # Copy the attributes (sorted by key) to the new item
        sortAttributes(item, newitem)

        # Copy the children of item (sorted) to the new item
        sortElements(list(item), newitem)

        # Append this sorted item to the sorted root
        newroot.append(newitem)


# has to sort all Cell and Point Data after the attribute "Name"!
def sortVTK(root):
    """Sort VTK file to be comparable (the order of nodes shouldn't matter)"""
    if root.tag != "VTKFile":
        print("Format is not a VTKFile. Sorting will most likely fail!")
    # create a new root for the sorted tree
    newroot = ET.Element(root.tag)
    # create the sorted copy
    # (after the idea of Dale Lane's xmldiff.py)
    sortAttributes(root, newroot)
    sortElements(list(root), newroot)
    # return the sorted element tree
    return newroot


def floatCompare(valueA, valueB, eps):
    """floating point comparison operator for scalars"""
    if math.fabs(valueA - valueB) < eps:
        return 0
    if valueA > valueB:
        return 1
    return -1


def floatVecCompare(valueA, valueB, eps):
    """floating point comparison operator for vectors"""
    for i, j in zip(valueA, valueB):
        res = floatCompare(i, j, eps)
        if res != 0:
            return res
    return 0


def sortVTKByCoordinates(root1, root2, verbose, convertedFromParallelVtu=False):
    """
    Sort VTK coordinates (the order of coordinates shouldn't matter)
    This usually occurs if different indexing is used (e.g. different grid managers)
    """
    if not isFuzzyEqualNode(
        root1.find(".//Points/DataArray"),
        root2.find(".//Points/DataArray"),
        absolute=1e-2,
        relative=1.5e-7,
        zeroValueThreshold={},
        verbose=False,
        convertedFromParallelVtu=False,
    ):
        if verbose:
            print("Sorting vtu by coordinates...")
        for root in [root1, root2]:
            # parse all DataArrays in a dictionary
            pointDataArrays = []
            cellDataArrays = []
            dataArrays = {}
            numberOfComponents = {}
            for dataArray in root.findall(".//PointData/DataArray"):
                pointDataArrays.append(dataArray.attrib["Name"])
            for dataArray in root.findall(".//CellData/DataArray"):
                cellDataArrays.append(dataArray.attrib["Name"])
            for dataArray in root.findall(".//DataArray"):
                dataArrays[dataArray.attrib["Name"]] = dataArray.text
                if dataArray.get("NumberOfComponents") is None:
                    numberOfComponents[dataArray.attrib["Name"]] = 1
                else:
                    numberOfComponents[dataArray.attrib["Name"]] = dataArray.attrib[
                        "NumberOfComponents"
                    ]

            vertexArray = []
            coords = dataArrays["Coordinates"].split()
            # group the coordinates into coordinate tuples
            dim = int(numberOfComponents["Coordinates"])

            # If the vtk file has been converted from pvd, vertices may be
            # duplicated. The following procedure eliminates the duplications.
            if convertedFromParallelVtu:
                uniqueIdx = []
                for i in range(len(coords) // dim):
                    pos = [float(c) for c in coords[(i * dim) : (i * dim + dim)]]
                    if pos in vertexArray:
                        uIdx = vertexArray.index(pos)
                    else:
                        uIdx = len(vertexArray)
                        vertexArray.append(pos)
                    uniqueIdx.append(uIdx)
            else:
                for i in range(len(coords) // dim):
                    vertexArray.append([float(c) for c in coords[(i * dim) : (i * dim + dim)]])

            # group the cells into vertex index tuples
            cellArray = []
            offsets = dataArrays["offsets"].split()
            connectivity = dataArrays["connectivity"].split()
            vertex = 0
            for cellIdx, offset in enumerate(offsets):
                cellArray.append([])
                for vIdx in range(vertex, int(offset)):
                    if convertedFromParallelVtu:
                        cellArray[cellIdx].append(uniqueIdx[int(connectivity[vIdx])])
                    else:
                        cellArray[cellIdx].append(int(connectivity[vIdx]))
                    vertex += 1

            # for non-conforming output vertices can have the same coordinates and also
            # different indices / sorting so we need another criterium to sort.
            # we use the largest cell midpoint coordinate vector the vertex is connected to
            largestCellMidPointForVertex = [[0, 0, 0]] * len(vertexArray)
            for cellIdx, cell in enumerate(cellArray):
                # compute cell midpoint
                coords = [vertexArray[i] for i in cell]
                midpoint = [i / float(len(coords)) for i in [sum(coord) for coord in zip(*coords)]]
                for vertexIndex in cell:
                    largestCellMidPointForVertex[vertexIndex] = max(
                        largestCellMidPointForVertex[vertexIndex], midpoint
                    )

            # first compare by coordinates, if the same compare largestCellMidPointForVertex
            def vertexCompare(valueA, valueB, largestCellMidPoint, bBoxMax, bBoxMin):
                epsilon = math.sqrt(sum((a - b) ** 2 for (a, b) in zip(bBoxMax, bBoxMin))) * 1e-7
                res = floatVecCompare(valueA[1], valueB[1], epsilon)
                if res != 0:
                    return res

                res2 = floatVecCompare(
                    largestCellMidPoint[valueA[0]],
                    largestCellMidPoint[valueB[0]],
                    epsilon,
                )
                if res2 != 0:
                    return res2

                return 0

            # obtain a vertex index map
            vMap = []
            for idx, coords in enumerate(vertexArray):
                vMap.append((idx, coords))

            # compute an epsilon and a comparison operator for floating point comparisons
            bBoxMax = max(vertexArray)
            bBoxMin = min(vertexArray)

            vertexIndexMap = [0] * len(vMap)
            vertexIndexMapInverse = [0] * len(vMap)
            # first sort by coordinates, if the same by largestCellMidPointForVertex
            for idxNew, idxOld in enumerate(
                sorted(
                    vMap,
                    key=functools.cmp_to_key(
                        functools.partial(
                            vertexCompare,
                            largestCellMidPoint=largestCellMidPointForVertex,
                            bBoxMax=bBoxMax,
                            bBoxMin=bBoxMin,
                        )
                    ),
                )
            ):
                vertexIndexMap[idxOld[0]] = idxNew
                vertexIndexMapInverse[idxNew] = idxOld[0]

            # replace all vertex indices in the cellArray by the new indices
            for i, cell in enumerate(cellArray):
                for j, vertexIndex in enumerate(cell):
                    cellArray[i][j] = vertexIndexMap[vertexIndex]

            # Sort the indices of all cells in case the two grids
            # have different orientation of the elements.
            # This doesn't necessarily have to be a valid vtk order,
            # it's just temporary for a sorted literal comparison of the files
            for i, cell in enumerate(cellArray):
                cellArray[i] = sorted(cell)

            # sort all data arrays
            for name, text in list(dataArrays.items()):
                # split the text
                items = text.split()
                # convert if vector
                num = int(numberOfComponents[name])
                newitems = []
                for i in range(len(items) // num):
                    newitems.append(list(items[i * num : i * num + num]))
                items = newitems
                # sort the items: we have either vertex or cell data
                if name in pointDataArrays:
                    # use the unique indices if the vtk file has been converted
                    # from pvd
                    if convertedFromParallelVtu:
                        uniqueItems = [None] * len(vertexArray)
                        for i, item in enumerate(items):
                            uniqueItems[uniqueIdx[i]] = item
                        sortedItems = [uniqueItems[i] for i in vertexIndexMapInverse]
                    else:
                        sortedItems = [items[i] for i in vertexIndexMapInverse]
                elif name in cellDataArrays or name == "types":
                    sortedItems = [j for (i, j) in sorted(zip(cellArray, items), key=itemgetter(0))]
                elif name == "offsets":
                    sortedItems = []
                    counter = 0
                    for cell in sorted(cellArray):
                        counter += len(cell)
                        sortedItems.append([str(counter)])
                elif name == "Coordinates":
                    sortedItems = [vertexArray[i] for i in vertexIndexMapInverse]
                elif name == "connectivity":
                    sortedItems = sorted(cellArray)

                # convert the sorted arrays to a xml text
                dataArrays[name] = ""
                for i in sortedItems:
                    for j in i:
                        dataArrays[name] += str(j) + " "

            # do the replacement in the actual elements
            for dataArray in root.findall(".//DataArray"):
                dataArray.text = dataArrays[dataArray.attrib["Name"]]

    return (root1, root2)


def compareData(
    dataFile1,
    dataFile2,
    delimiter,
    absolute=1.5e-7,
    relative=1e-2,
    zeroValueThreshold=None,
    ignoreFields=None,
    verbose=True,
):
    """take two data files and compare them. Returns an exit key as returnvalue.

    Arguments:
    ----------
    dataFile1, dataFile2 : string
        The filenames of the data files to compare
    delimiter: string
        The delimiter for the columns

    Keyword Arguments:
    ------------------
    absolute : float
        The epsilon used for comparing numbers with an absolute criterion
    relative: float
        The epsilon used for comparing numbers with an relative criterion
    zeroValueThreshold: dict
        A dictionary of parameter value pairs that set the threshold under
        which a number is treated as zero for a certain parameter. Use this parameter if
        you have to avoid comparisons of very small numbers for a certain parameter.
    ignoreFields: list
        A list of field names to be ignored in the comparison
    verbose : bool
        If the script should produce informative output. Enabled by default as the details
        give the tester a lot more information on why tests fail.
    """

    if verbose:
        print(
            f"Comparing {dataFile1} and {dataFile2}\n"
            f"... with a maximum relative error of {relative} and "
            f"a maximum absolute error of {absolute}*max_abs_parameter_value."
        )

    zeroValueThreshold = zeroValueThreshold or {}

    # implement ignoring fields by setting a very high threshold
    if ignoreFields is not None:
        for field in ignoreFields:
            zeroValueThreshold[field] = 1e100

    # construct element tree from data files
    with open(dataFile1, "r") as data1:
        data1 = list(csv.reader(data1, delimiter=delimiter))
    with open(dataFile1, "r") as data2:
        data2 = list(csv.reader(data2, delimiter=delimiter))

    if len(data1) != len(data2):
        print(
            "Length of data1 and data2 not equal: ref=",
            len(data1),
            ",new=",
            len(data2),
            ". Aborting!",
        )
        sys.exit(3)

    isEqual = True
    for i in range(0, len(data1[0])):
        valueA = data1[0][i]
        valueB = data2[0][i]
        for j in range(1, len(data1)):
            valueA += f" {data1[j][i]}"
            valueB += f" {data2[j][i]}"

        if not isFuzzyEqualText(
            valueA,
            valueB,
            f"row {i}",
            len(data1),
            absolute,
            relative,
            zeroValueThreshold,
            verbose,
        ):
            if verbose:
                isEqual = False
            else:
                return False

    return 0 if isEqual else 1
