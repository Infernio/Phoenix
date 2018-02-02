#----------------------------------------------------------------------
# Name:        wx.tools.pywxrc
# Purpose:     XML resource compiler
#
# Author:      Robin Dunn
#              Based on wxrc.cpp by Vaclav Slavik, Eduardo Marques
#              Ported to Python in order to not require yet another
#              binary in wxPython distributions
#
#              Massive rework by Eli Golovinsky
#
#              Editable blocks by Roman Rolinsky
#
# Copyright:   (c) 2004-2017 by Total Control Software, 2000 Vaclav Slavik
# Licence:     wxWindows license
# Tags:        phoenix-port
#----------------------------------------------------------------------

"""
pywxrc -- Python XML resource compiler
          (see http://wiki.wxpython.org/index.cgi/pywxrc for more info)

Usage: python pywxrc.py -h
       python pywxrc.py [-p] [-g] [-e] [-v] [-o filename] xrc input files...

  -h, --help     show help message
  -p, --python   generate python module
  -g, --gettext  output list of translatable strings (may be combined with -p)
  -e, --embed    embed XRC resources in the output file
  -v, --novar    suppress default assignment of variables
  -o, --output   output filename, or - for stdout
"""

import sys, os, getopt, glob, re
import xml.dom.minidom as minidom
from six import print_

#----------------------------------------------------------------------

reBeginBlock = re.compile(r'^#!XRCED:begin-block:(\S+)')
reEndBlock = re.compile(r'^#!XRCED:end-block:(\S+)')

class PythonTemplates:
    FILE_HEADER = """\
# This file was automatically generated by pywxrc.
# -*- coding: UTF-8 -*-

import wx
import wx.xrc as xrc

__res = None

def get_resources():
    \"\"\" This function provides access to the XML resources in this module.\"\"\"
    global __res
    if __res == None:
        __init_resources()
    return __res

"""

    CLASS_HEADER = """\
class xrc%(windowName)s(wx.%(windowClass)s):
#!XRCED:begin-block:xrc%(windowName)s.PreCreate
    def PreCreate(self, pre):
        \"\"\" This function is called during the class's initialization.

        Override it for custom setup before the window is created usually to
        set additional window styles using SetWindowStyle() and SetExtraStyle().
        \"\"\"
        pass

#!XRCED:end-block:xrc%(windowName)s.PreCreate

    def __init__(self, parent):
        # Two stage creation (see http://wiki.wxpython.org/index.cgi/TwoStageCreation)
        wx.%(windowClass)s.__init__(self)
        self.PreCreate(self)
        get_resources().Load%(windowClass)s(self, parent, "%(windowName)s")

        # Define variables for the controls, bind event handlers
"""

    SUBCLASS_HEADER = """\
class %(subclass)s(wx.%(windowClass)s):
    def __init__(self):
        # Two stage creation (see http://wiki.wxpython.org/index.cgi/TwoStageCreation)
        wx.%(windowClass)s.__init__(self)
        self.Bind(wx.EVT_WINDOW_CREATE, self.OnCreate)

#!XRCED:begin-block:%(subclass)s._PostInit
    def _PostInit(self):
        \"\"\" This function is called after the subclassed object is created.

        Override it for custom setup before the window is created usually to
        set additional window styles using SetWindowStyle() and SetExtraStyle().
        \"\"\"
        pass
#!XRCED:end-block:%(subclass)s._PostInit

    def OnCreate(self, evt):
        self.Unbind(wx.EVT_WINDOW_CREATE)
        self._PostInit()
"""

    CREATE_WIDGET_VAR = """\
        self.%(widgetName)s = xrc.XRCCTRL(self, \"%(widgetName)s\")
"""

    FRAME_MENUBAR_VAR = """\
        self.%(widgetName)s = self.GetMenuBar()
"""

    FRAME_MENUBAR_MENUITEM_VAR = """\
        self.%(widgetName)s = self.GetMenuBar().FindItemById(xrc.XRCID(\"%(widgetName)s\"))
"""

    FRAME_MENUBAR_MENU_VAR = """\
        idx = self.GetMenuBar().FindMenu(\"%(label)s\")
        if idx != wx.NOT_FOUND:
            self.%(widgetName)s = self.GetMenuBar().GetMenu(idx)
        else:
            self.%(widgetName)s = self.GetMenuBar().FindItemById(xrc.XRCID(\"%(widgetName)s\")).GetSubMenu()
"""


    MENUBAR_MENUITEM_VAR = """\
        self.%(widgetName)s = self.FindItemById(xrc.XRCID(\"%(widgetName)s\"))
"""

    MENUBAR_MENU_VAR = """\
        idx = self.FindMenu(\"%(label)s\")
        if idx != wx.NOT_FOUND:
            self.%(widgetName)s = self.GetMenu(idx)
        else:
            self.%(widgetName)s = self.FindItemById(xrc.XRCID(\"%(widgetName)s\")).GetSubMenu()
"""

    MENU_MENUITEM_VAR = """\
        self.%(widgetName)s = self.FindItemById(xrc.XRCID(\"%(widgetName)s\"))
"""

    MENU_MENU_VAR = """\
        self.%(widgetName)s = self.FindItemById(xrc.XRCID(\"%(widgetName)s\")).GetSubMenu()
"""

    FRAME_TOOLBAR_VAR = """\
        self.%(widgetName)s = self.GetToolBar()
"""

    FRAME_TOOLBAR_TOOL_VAR = """\
        self.%(widgetName)s = self.GetToolBar().FindById(xrc.XRCID(\"%(widgetName)s\"))
"""

    TOOLBAR_TOOL_VAR = """\
        self.%(widgetName)s = self.FindById(xrc.XRCID(\"%(widgetName)s\"))
"""

    BIND_WIDGET_EVENT = """\
        self.Bind(wx.%(event)s, self.%(eventHandler)s, %(eventObject)s)
"""

    BIND_EVENT = """\
        self.Bind(wx.%(event)s, self.%(eventHandler)s)
"""

    CREATE_EVENT_HANDLER = """\
#!XRCED:begin-block:xrc%(windowName)s.%(eventHandler)s
    def %(eventHandler)s(self, evt):
        # Replace with event handler code
        print(\"%(eventHandler)s()\")
#!XRCED:end-block:xrc%(windowName)s.%(eventHandler)s
"""

    MENU_CLASS_HEADER = """\
class xrc%(windowName)s(wx.%(windowClass)s):
    def __init__(self):
        pre = get_resources().LoadMenu("%(windowName)s")

        # This is a copy of Robin's PostCreate voodoo magic in wx.Window that
        # relinks the self object with the menu object.
        self.this = pre.this
        self.thisown = pre.thisown
        pre.thisown = 0
        if hasattr(self, '_setOORInfo'):
            self._setOORInfo(self)

        # Define variables for the menu items
"""

    MENUBAR_CLASS_HEADER = """\
class xrc%(windowName)s(wx.%(windowClass)s):
    def __init__(self):
        pre = get_resources().LoadMenuBar("%(windowName)s")
        self.PostCreate(pre)

        # Define variables for the menu items
"""

    TOOLBAR_CLASS_HEADER = """\
class xrc%(windowName)s(wx.%(windowClass)s):
    def __init__(self, parent):
        pre = get_resources().LoadToolBar(parent, "%(windowName)s")
        self.PostCreate(pre)

        # Define variables for the toolbar items
"""

    INIT_RESOURE_HEADER = """\
# ------------------------ Resource data ----------------------

def __init_resources():
    global __res
    __res = xrc.XmlResource()
"""

    LOAD_RES_FILE = """\
    __res.Load('%(resourceFilename)s')"""

    FILE_AS_STRING = """\
    %(filename)s = '''\\
%(fileData)s'''

"""

    PREPARE_MEMFS = """\
    wx.FileSystem.AddHandler(wx.MemoryFSHandler())
"""

    ADD_FILE_TO_MEMFS = """\
    wx.MemoryFSHandler.AddFile('XRC/%(memoryPath)s/%(filename)s', %(filename)s)
"""

    LOAD_RES_MEMFS = """\
    __res.Load('memory:XRC/%(memoryPath)s/%(resourceFilename)s')
"""

    GETTEXT_DUMMY_FUNC = """
# ----------------------- Gettext strings ---------------------

def __gettext_strings():
    # This is a dummy function that lists all the strings that are used in
    # the XRC file in the _("a string") format to be recognized by GNU
    # gettext utilities (specificaly the xgettext utility) and the
    # mki18n.py script.  For more information see:
    # http://wiki.wxpython.org/index.cgi/Internationalization

    def _(str): pass

%s
"""

#----------------------------------------------------------------------

class XmlResourceCompiler:

    templates = PythonTemplates()

    """This class generates Python code from XML resource files (XRC)."""

    def MakePythonModule(self, inputFiles, outputFilename,
                         embedResources=False, generateGetText=False,
                         assignVariables=True):

        self.blocks = {}
        self.outputFilename = outputFilename
        outputFile = self._OpenOutputFile(outputFilename)
        self.assignVariables = assignVariables

        classes = []
        subclasses = []
        resources = []
        gettextStrings = []

        # process all the inputFiles, collecting the output data
        for inFile in inputFiles:
            resourceDocument = minidom.parse(inFile)
            subclasses.append(self.GenerateSubclasses(resourceDocument))
            classes.append(self.GenerateClasses(resourceDocument))

            if embedResources:
                res = self.GenerateInitResourcesEmbedded(inFile, resourceDocument)
            else:
                res = self.GenerateInitResourcesFile(inFile, resourceDocument)
            resources.append(res)

            if generateGetText:
                gettextStrings += self.FindStringsInNode(resourceDocument.firstChild)

        # now write it all out
        print_(self.templates.FILE_HEADER, file=outputFile)

        # Note: Technically it is not legal to have anything other
        # than ascii for class and variable names, but since the user
        # can create the XML with non-ascii names we'll go ahead and
        # allow for it here, and then let Python complain about it
        # later when they try to run the program.
        if subclasses:
            subclasses = self.ReplaceBlocks(u"\n".join(subclasses))
            print_(subclasses.encode("UTF-8"), file=outputFile)
        if classes:
            classes = self.ReplaceBlocks(u"\n".join(classes))
            print_(classes.encode("UTF-8"), file=outputFile)

        print_(self.templates.INIT_RESOURE_HEADER, file=outputFile)
        if embedResources:
            print_(self.templates.PREPARE_MEMFS, file=outputFile)
        resources = u"\n".join(resources)
        print_(resources.encode("UTF-8"), file=outputFile)

        if generateGetText:
            # These have already been converted to utf-8...
            gettextStrings = ['    _("%s")' % s for s in gettextStrings]
            gettextStrings = "\n".join(gettextStrings)
            print_(self.templates.GETTEXT_DUMMY_FUNC % gettextStrings, file=outputFile)

    #-------------------------------------------------------------------

    def MakeGetTextOutput(self, inputFiles, outputFilename):
        """
        Just output the gettext strings by themselves, with no other
        code generation.
        """
        outputFile = self._OpenOutputFile(outputFilename)
        for inFile in inputFiles:
            resourceDocument = minidom.parse(inFile)
            resource = resourceDocument.firstChild
            strings = self.FindStringsInNode(resource)
            strings = ['_("%s");' % s for s in strings]
            print_("\n".join(strings), file=outputFile)

    #-------------------------------------------------------------------

    def GenerateClasses(self, resourceDocument):
        outputList = []

        resource = resourceDocument.firstChild
        topWindows = [e for e in resource.childNodes
                      if e.nodeType == e.ELEMENT_NODE and e.tagName == "object" \
                      and not e.getAttribute('subclass')]

        # Generate a class for each top-window object (Frame, Panel, Dialog, etc.)
        for topWindow in topWindows:
            windowClass = topWindow.getAttribute("class")
            windowClass = re.sub("^wx", "", windowClass)
            windowName = topWindow.getAttribute("name")
            if not windowName: continue

            if windowClass in ["MenuBar"]:
                genfunc = self.GenerateMenuBarClass
            elif windowClass in ["Menu"]:
                genfunc = self.GenerateMenuClass
            elif windowClass in ["ToolBar"]:
                genfunc = self.GenerateToolBarClass
            else:
                genfunc = self.GenerateWidgetClass

            vars = []
            outputList += genfunc(windowClass, windowName, topWindow, vars)
            outputList.append('\n')

            outputList += self.GenerateEventHandlers(windowClass, windowName, topWindow, vars)

        return "".join(outputList)

    #-------------------------------------------------------------------

    def CheckAssignVar(self, widget):
        if self.assignVariables: return True # assign_var override mode
        assign_var = False
        for node in widget.getElementsByTagName("XRCED"):
            if node.parentNode is widget:
                try:
                    elem = node.getElementsByTagName("assign_var")[0]
                except IndexError:
                    continue
                if elem.childNodes:
                    ch = elem.childNodes[0]
                    if ch.nodeType == ch.TEXT_NODE and bool(ch.nodeValue):
                        assign_var = True
        return assign_var


    def GenerateMenuBarClass(self, windowClass, windowName, topWindow, vars):
        outputList = []

        # output the header
        outputList.append(self.templates.MENUBAR_CLASS_HEADER % locals())

        # create an attribute for menus and menu items that have names
        for widget in topWindow.getElementsByTagName("object"):
            if not self.CheckAssignVar(widget): continue
            widgetClass = widget.getAttribute("class")
            widgetClass = re.sub("^wx", "", widgetClass)
            widgetName = widget.getAttribute("name")
            if widgetName != "" and widgetClass != "":
                vars.append(widgetName)
                if widgetClass == "MenuItem":
                    outputList.append(self.templates.MENUBAR_MENUITEM_VAR % locals())
                elif widgetClass == "Menu":
                    label = widget.getElementsByTagName("label")[0]
                    label = label.childNodes[0].data
                    outputList.append(self.templates.MENUBAR_MENU_VAR % locals())
                else:
                    raise RuntimeError("Unexpected widgetClass for MenuBar: %s" % widgetClass)

        return outputList


    def GenerateMenuClass(self, windowClass, windowName, topWindow, vars):
        outputList = []

        # output the header
        outputList.append(self.templates.MENU_CLASS_HEADER % locals())
        for widget in topWindow.getElementsByTagName("object"):
            if not self.CheckAssignVar(widget): continue
            widgetClass = widget.getAttribute("class")
            widgetClass = re.sub("^wx", "", widgetClass)
            widgetName = widget.getAttribute("name")
            if widgetName != "" and widgetClass != "":
                vars.append(widgetName)
                if widgetClass == "MenuItem":
                    outputList.append(self.templates.MENU_MENUITEM_VAR % locals())
                elif widgetClass == "Menu":
                    label = widget.getElementsByTagName("label")[0]
                    label = label.childNodes[0].data
                    outputList.append(self.templates.MENU_MENU_VAR % locals())
                else:
                    raise RuntimeError("Unexpected widgetClass for Menu: %s" % widgetClass)

        return outputList


    def GenerateToolBarClass(self, windowClass, windowName, topWindow, vars):
        outputList = []

        # output the header
        outputList.append(self.templates.TOOLBAR_CLASS_HEADER % locals())

        # create an attribute for menus and menu items that have names
        for widget in topWindow.getElementsByTagName("object"):
            if not self.CheckAssignVar(widget): continue
            widgetClass = widget.getAttribute("class")
            widgetClass = re.sub("^wx", "", widgetClass)
            widgetName = widget.getAttribute("name")
            if widgetName != "" and widgetClass != "":
                vars.append(widgetName)
                if widgetClass == "tool":
                    outputList.append(self.templates.TOOLBAR_TOOL_VAR % locals())
                else:
                    raise RuntimeError("Unexpected widgetClass for ToolBar: %s" % widgetClass)

        return outputList


    def GenerateWidgetClass(self, windowClass, windowName, topWindow, vars):
        outputList = []

        # output the header
        outputList.append(self.templates.CLASS_HEADER % locals())

        # Generate an attribute for each named item in the container
        for widget in topWindow.getElementsByTagName("object"):
            if not self.CheckAssignVar(widget): continue
            widgetClass = widget.getAttribute("class")
            widgetClass = re.sub("^wx", "", widgetClass)
            widgetName = widget.getAttribute("name")
            if widgetName != "" and widgetClass != "":
                vars.append(widgetName)
                if widgetClass not in \
                       ['tool', 'unknown', 'notebookpage', 'separator',
                        'sizeritem', 'Menu', 'MenuBar', 'MenuItem']:
                    outputList.append(self.templates.CREATE_WIDGET_VAR % locals())
                elif widgetClass == "MenuBar":
                    outputList.append(self.templates.FRAME_MENUBAR_VAR % locals())
                elif widgetClass == "MenuItem":
                    outputList.append(self.templates.FRAME_MENUBAR_MENUITEM_VAR % locals())
                elif widgetClass == "Menu":
                    label = widget.getElementsByTagName("label")[0]
                    label = label.childNodes[0].data
                    outputList.append(self.templates.FRAME_MENUBAR_MENU_VAR % locals())
                elif widgetClass == "ToolBar":
                    outputList.append(self.templates.FRAME_TOOLBAR_VAR % locals())
                elif widgetClass == "tool":
                    outputList.append(self.templates.FRAME_TOOLBAR_TOOL_VAR % locals())

        return outputList

    #-------------------------------------------------------------------

    def GenerateSubclasses(self, resourceDocument):
        outputList = []

        objectNodes = resourceDocument.getElementsByTagName("object")
        subclasses = set()
        bases = {}
        baseName = os.path.splitext(self.outputFilename)[0]
        for node in objectNodes:
            subclass = node.getAttribute('subclass')
            if subclass:
                module = subclass[:subclass.find('.')]
                if module != baseName: continue
                klass = node.getAttribute("class")
                if subclass not in subclasses:
                    subclasses.add(subclass)
                    bases[subclass] = klass
                else:
                    if klass != bases[subclass]:
                        print('pywxrc: error: conflicting base classes for subclass %(subclass)s' % subclass)

        # Generate subclasses
        for subclass in subclasses:
            windowClass = bases[subclass]
            subclass = re.sub("^\S+\.", "", subclass)
            windowClass = re.sub("^wx", "", windowClass)
            outputList.append(self.templates.SUBCLASS_HEADER % locals())
            outputList.append('\n')

        return "".join(outputList)

    #-------------------------------------------------------------------

    def GenerateEventHandlers(self, windowClass, windowName, topWindow, vars):
        outputList = []

        # Generate child event handlers
        eventHandlers = []
        for elem in topWindow.getElementsByTagName("XRCED"):
            try:
                eventNode = elem.getElementsByTagName("events")[0]
            except IndexError:
                continue
            events = eventNode.childNodes[0].data.split('|')
            for event in events:
                if elem.parentNode is topWindow:
                    eventHandler = "On%s" % event[4:].capitalize()
                    outputList.append(self.templates.BIND_EVENT % locals())
                    eventHandlers.append(eventHandler)
                else:
                    widget = elem.parentNode
                    widgetClass = widget.getAttribute("class")
                    widgetClass = re.sub("^wx", "", widgetClass)
                    widgetName = widget.getAttribute("name")
                    if not widgetName or not widgetClass: continue
                    eventObject = None
                    if widgetClass == "MenuItem" and windowClass != "MenuBar":
                        if widgetName[:2] == "wx":
                            eventObject = 'id=wx.%s' % re.sub("^wx", "", widgetName)
                        eventHandler = "On%s_%s" % (event[4:].capitalize(), widgetName)
                        if widgetName in vars: eventObject = "self.%s" % widgetName
                    else:
                        eventHandler = "On%s_%s" % (event[4:].capitalize(), widgetName)
                        if widgetName in vars: eventObject = "self.%s" % widgetName
                    if not eventObject:
                        eventObject = "id=xrc.XRCID('%s')" % widgetName
                    outputList.append(self.templates.BIND_WIDGET_EVENT % locals())
                    eventHandlers.append(eventHandler)
        outputList.append("\n")

        for eventHandler in eventHandlers:
            block = "xrc%(windowName)s.%(eventHandler)s" % locals()
            try:
                outputList.append(self.blocks[block])
            except KeyError:
                outputList.append(self.templates.CREATE_EVENT_HANDLER % locals())
            outputList.append("\n")

        outputList.append("\n")
        return "".join(outputList)

    #-------------------------------------------------------------------

    def GenerateInitResourcesEmbedded(self, resourceFilename, resourceDocument):
        outputList = []
        files = []

        resourcePath = os.path.split(resourceFilename)[0]
        memoryPath = self.GetMemoryFilename(os.path.splitext(os.path.split(resourceFilename)[1])[0])
        resourceFilename = self.GetMemoryFilename(os.path.split(resourceFilename)[1])

        self.ReplaceFilenamesInXRC(resourceDocument.firstChild, files, resourcePath)

        filename = resourceFilename
        fileData = resourceDocument.toxml() # what about this? encoding=resourceDocument.encoding)
        outputList.append(self.templates.FILE_AS_STRING % locals())

        for f in files:
            filename = self.GetMemoryFilename(f)
            fileData = self.FileToString(os.path.join(resourcePath, f))
            outputList.append(self.templates.FILE_AS_STRING % locals())

        for f in [resourceFilename] + files:
            filename = self.GetMemoryFilename(f)
            outputList.append(self.templates.ADD_FILE_TO_MEMFS % locals())

        outputList.append(self.templates.LOAD_RES_MEMFS % locals())

        return "".join(outputList)

    #-------------------------------------------------------------------

    def GenerateInitResourcesFile(self, resourceFilename, resourceDocument):
        # take only the filename portion out of resourceFilename
        resourceFilename = os.path.split(resourceFilename)[1]
        outputList = []
        outputList.append(self.templates.LOAD_RES_FILE % locals())
        return "".join(outputList)

    #-------------------------------------------------------------------

    def GetMemoryFilename(self, filename):
        # Remove special chars from the filename
        return re.sub(r"[^A-Za-z0-9_]", "_", filename)

    #-------------------------------------------------------------------

    def FileToString(self, filename):
        outputList = []

        buffer = open(filename, "rb").read()
        fileLen = len(buffer)

        linelng = 0
        for i in xrange(fileLen):
            s = buffer[i]
            c = ord(s)
            if s == '\n':
                tmp = s
                linelng = 0
            elif c < 32 or c > 127 or s == "'":
                tmp = "\\x%02x" % c
            elif s == "\\":
                tmp = "\\\\"
            else:
                tmp = s

            if linelng > 70:
                linelng = 0
                outputList.append("\\\n")

            outputList.append(tmp)
            linelng += len(tmp)

        return "".join(outputList)

    #-------------------------------------------------------------------

    def NodeContainsFilename(self, node):
        """ Does 'node' contain filename information at all? """

        # Any bitmaps:
        if node.nodeName == "bitmap":
            return True

        if node.nodeName == "icon":
            return True

        # URLs in wxHtmlWindow:
        if node.nodeName == "url":
            return True

        # wxBitmapButton:
        parent = node.parentNode
        if parent.__class__ != minidom.Document and \
           parent.getAttribute("class") == "wxBitmapButton" and \
           (node.nodeName == "focus" or node.nodeName == "disabled" or
            node.nodeName == "selected"):
            return True

        # wxBitmap or wxIcon toplevel resources:
        if node.nodeName == "object":
            klass = node.getAttribute("class")
            if klass == "wxBitmap" or klass == "wxIcon":
                return True

        return False

    #-------------------------------------------------------------------

    def ReplaceFilenamesInXRC(self, node, files, resourcePath):
        """ Finds all files mentioned in resource file, e.g. <bitmap>filename</bitmap>
        and replaces them with the memory filenames.

        Fills a list of the filenames found."""

        # Is 'node' XML node element?
        if node is None: return
        if node.nodeType != minidom.Document.ELEMENT_NODE: return

        containsFilename = self.NodeContainsFilename(node);

        for n in node.childNodes:

            if (containsFilename and
                (n.nodeType == minidom.Document.TEXT_NODE or
                 n.nodeType == minidom.Document.CDATA_SECTION_NODE)):

                filename = n.nodeValue
                memoryFilename = self.GetMemoryFilename(filename)
                n.nodeValue = memoryFilename

                if filename not in files:
                    files.append(filename)

            # Recurse into children
            if n.nodeType == minidom.Document.ELEMENT_NODE:
                self.ReplaceFilenamesInXRC(n, files, resourcePath);

    #-------------------------------------------------------------------

    def FindStringsInNode(self, parent):
        def is_number(st):
            try:
                i = int(st)
                return True
            except ValueError:
                return False

        strings = []
        if parent is None:
            return strings;

        for child in parent.childNodes:
            if ((parent.nodeType == parent.ELEMENT_NODE) and
                # parent is an element, i.e. has subnodes...
                (child.nodeType == child.TEXT_NODE or
                child.nodeType == child.CDATA_SECTION_NODE) and
                # ...it is textnode...
                (
                    parent.tagName == "label" or
                    (parent.tagName == "value" and
                                   not is_number(child.nodeValue)) or
                    parent.tagName == "help" or
                    parent.tagName == "longhelp" or
                    parent.tagName == "tooltip" or
                    parent.tagName == "htmlcode" or
                    parent.tagName == "title" or
                    parent.tagName == "item"
                )):
                # ...and known to contain translatable string
                if (parent.getAttribute("translate") != "0"):
                    strings.append(self.ConvertText(child.nodeValue))

            # subnodes:
            if child.nodeType == child.ELEMENT_NODE:
                strings += self.FindStringsInNode(child)

        return strings

    #-------------------------------------------------------------------

    def ConvertText(self, st):
        st2 = ""
        dt = list(st)

        skipNext = False
        for i in range(len(dt)):
            if skipNext:
                skipNext = False
                continue

            if dt[i] == '_':
                if dt[i+1] == '_':
                    st2 += '_'
                    skipNext = True
                else:
                    st2 += '&'
            elif dt[i] == '\n':
                st2 += '\\n'
            elif dt[i] == '\t':
                st2 += '\\t'
            elif dt[i] == '\r':
                st2 += '\\r'
            elif dt[i] == '\\':
                if dt[i+1] not in ['n', 't', 'r']:
                    st2 += '\\\\'
                else:
                    st2 += '\\'
            elif dt[i] == '"':
                st2 += '\\"'
            else:
                st2 += dt[i]

        return st2.encode("UTF-8")

    #-------------------------------------------------------------------

    # Replace editable block contents with previous
    def ReplaceBlocks(self, input):
        output = []
        block = None
        blockLines = []
        for l in input.split('\n'):
            if not block:
                mo = reBeginBlock.match(l)
                if mo and mo.groups()[0] in self.blocks:
                    block = mo.groups()[0]
                    output.append(self.blocks[block])
                else:
                    output.append(l + '\n')
            else:
                mo = reEndBlock.match(l)
                if mo:
                    if mo.groups()[0] != block:
                        print("pywxrc: error: block mismatch: %s != %s" % (block, mo.groups()[0]))
                    block = None
        return ''.join(output)

    #-------------------------------------------------------------------

    def _OpenOutputFile(self, outputFilename):
        if outputFilename == "-":
            outputFile = sys.stdout
        else:
            # Parse existing file to collect editable blocks
            if os.path.isfile(outputFilename):
                outputFile = open(outputFilename)
                block = None
                blockLines = []
                for l in outputFile.readlines():
                    if not block:
                        mo = reBeginBlock.match(l)
                        if mo:
                            block = mo.groups()[0]
                            blockLines = [l]
                    else:
                        blockLines.append(l)
                        mo = reEndBlock.match(l)
                        if mo:
                            if mo.groups()[0] != block:
                                print("pywxrc: error: block mismatch: %s != %s" % (block, mo.groups()[0]))
                            self.blocks[block] = "".join(blockLines)
                            block = None

            try:
                outputFile = open(outputFilename, "wt")
            except IOError:
                raise IOError("Can't write output to '%s'" % outputFilename)
        return outputFile





#---------------------------------------------------------------------------

def main(args=None):
    if not args:
        args = sys.argv[1:]

    resourceFilename = ""
    outputFilename = None
    embedResources = False
    generateGetText = False
    assignVariables = True
    generatePython = False

    try:
        opts, args = getopt.gnu_getopt(args,
                                       "hpgevo:",
                                       "help python gettext embed novar output=".split())
    except getopt.GetoptError as exc:
        print("\nError : %s\n" % str(exc))
        print(__doc__)
        sys.exit(1)

    # If there is no input file argument, show help and exit
    if not args:
        print(__doc__)
        print("No xrc input file was specified.")
        sys.exit(1)

    # Parse options and arguments
    for opt, val in opts:
        if opt in ["-h", "--help"]:
            print(__doc__)
            sys.exit(1)

        if opt in ["-p", "--python"]:
            generatePython = True

        if opt in ["-o", "--output"]:
            outputFilename = val

        if opt in ["-e", "--embed"]:
            embedResources = True

        if opt in ["-v", "--novar"]:
            assignVariables = False

        if opt in ["-g", "--gettext"]:
            generateGetText = True


    # check for and expand any wildcards in the list of input files
    inputFiles = []
    for arg in args:
        inputFiles += glob.glob(arg)


    comp = XmlResourceCompiler()

    try:
        if generatePython:
            if not outputFilename:
                outputFilename = os.path.splitext(args[0])[0] + "_xrc.py"
            comp.MakePythonModule(inputFiles, outputFilename,
                                  embedResources, generateGetText,
                                  assignVariables)

        elif generateGetText:
            if not outputFilename:
                outputFilename = '-'
            comp.MakeGetTextOutput(inputFiles, outputFilename)

        else:
            print(__doc__)
            print("One or both of -p, -g must be specified.")
            sys.exit(1)


    except IOError as exc:
        print_("%s." % str(exc), file=sys.stderr)
    else:
        if outputFilename != "-":
            print_("Resources written to %s." % outputFilename, file=outputFilename)

if __name__ == "__main__":
    main(sys.argv[1:])
