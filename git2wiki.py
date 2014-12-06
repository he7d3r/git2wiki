#!/usr/bin/python
# -*- coding: utf-8  -*-
""" Script to sync git repositories with wiki pages """
# Requirements
# sudo npm install uglify-js -g
# sudo pip install PyExecJS
# sudo pip install uglipyjs

import pywikibot
import os
import execjs
import uglipyjs

def main(*args):
    tracking = False
    gitHubUser = False
    rootDir = os.getcwd()
    gitHubUrl = 'https://github.com/%s'
    # FIXME: Add git hash/version as in
    # "Sync with https://github.com/FOO/BAR (v9.9.9 or HASH)"
    gitHubSummary = u'Sync with %s'
    # FIXME: Add UglifyJS version as in
    # "minify with UglifyJS v9.9.9"
    uglifyjsSummary = u'minify with UglifyJS'
    for arg in pywikibot.handleArgs():
        if arg == "-all":
            allowNullEdits = True
        elif arg == "-track":
            # The file link is unnecessary on GitHub but useful on wiki
            tracking = u'[[File:%s]] (workaround for [[bugzilla:33355]])'
        elif arg.startswith('-prefix:'):
            userPrefix = arg[len('-prefix:'):]
        elif arg.startswith('-mypath:'):
            rootDir = arg[len('-mypath:'):]
        elif arg.startswith('-github:'):
            gitHubUser = arg[len('-github:'):]
    if not gitHubUser:
        print( 'Missing required paramenter -github:<username>.' )
        return
    gitHubUrl = ( gitHubUrl % gitHubUser ) + '/%s'
    site = pywikibot.getSite() # pywikibot.Site( 'meta', 'wikimedia' )
    for dirpath, dirnames, files in os.walk(rootDir):
        for name in files:
            ext = name.rsplit( '.', 1 )[-1].lower()
            # Assume the structure is <mypath>/<repo>/src/<title.(js|css)>
            if ext in [ 'js', 'css' ] and dirpath.endswith( '/src' ):
                # FIXME: Skip unchanged files (use git status?)
                # Check for allowNullEdits
                title = userPrefix + name
                repo = dirpath.rsplit( '/', 2 )[-2]
                summary = gitHubSummary % ( gitHubUrl % repo )
                code = open( os.path.join( dirpath, name ), 'r' ).read()
                if ext == 'js':
                    try:
                        minCode = uglipyjs.compile( code ).decode('utf-8')
                        summary = summary + '; ' + uglifyjsSummary
                    except execjs.ProgramError:
                        minCode = code.decode('utf-8')
                    minCode = '// <nowiki>\n' + minCode + '\n// </nowiki>'
                    if tracking:
                        minCode = u'// ' + ( tracking % title ) + u'\n' + minCode
                else:
                    minCode = '/* <nowiki> */\n' + code.decode('utf-8') + '\n/* </nowiki> */'
                    if tracking:
                        minCode = u'/* ' + ( tracking % title ) + u' */\n' + minCode
                page = pywikibot.Page( site, title )
                page.text = minCode
                page.save( summary )
if __name__ == '__main__':
    main()
