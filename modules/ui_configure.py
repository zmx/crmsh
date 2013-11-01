# Copyright (C) 2008-2011 Dejan Muhamedagic <dmuhamedagic@suse.de>
# Copyright (C) 2013 Kristoffer Gronlund <kgronlund@suse.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#

import command
import utils
import vars
import xmlutil
from cibconfig import mkset_obj, CibFactory
from msg import UserPrefs, Options, ErrorBuffer
from msg import common_err, common_info, common_warn
from msg import syntax_err
import rsctest
import ui_cib
import ui_cibstatus
import ui_ra
import ui_template
import ui_history
import ui_utils


class CibConfig(command.UI):
    '''
    The configuration class
    '''
    name = "configure"

    def __init__(self):
        command.UI.__init__(self)
        if options.interactive:
            cib_factory.initialize()

    def requires(self):
        # see the configure ptest/simulate command
        has_ptest = utils.is_program('ptest')
        has_simulate = utils.is_program('crm_simulate')
        if not has_ptest:
            vars.simulate_programs["ptest"] = "crm_simulate"
        if not has_simulate:
            vars.simulate_programs["simulate"] = "ptest"
        if not (has_ptest or has_simulate):
            common_warn("neither ptest nor crm_simulate exist, check your installation")
            vars.simulate_programs["ptest"] = ""
            vars.simulate_programs["simulate"] = ""

    @command.name('_test')
    @command.skill_level('administrator')
    def do_check_structure(self, context):
        return cib_factory.check_structure()

    @command.name('_regtest')
    @command.skill_level('administrator')
    def do_regression_testing(self, context, param):
        return cib_factory.regression_testing(param)

    @command.name('_objects')
    @command.skill_level('administrator')
    def do_showobjects(self, context):
        cib_factory.showobjects()

    @command.level(ui_ra.RA)
    def do_ra(self):
        pass

    @command.level(ui_cib.CibShadow)
    def do_cib(self):
        pass

    @command.level(ui_cibstatus.CibStatusUI)
    def do_cibstatus(self):
        pass

    @command.level(ui_template.Template)
    def do_template(self):
        pass

    @command.level(ui_history.History)
    def do_history(self):
        pass

    @command.skill_level('administrator')
    def do_show(self, context, *args):
        "usage: show [xml] [<id>...]"
        if not cib_factory.is_cib_sane():
            return False
        set_obj = mkset_obj(*args)
        return set_obj.show()

    @command.skill_level('administrator')
    def do_filter(self, context, filter, *args):
        "usage: filter <prog> [xml] [<id>...]"
        if not cib_factory.is_cib_sane():
            return False
        set_obj = mkset_obj(*args)
        return set_obj.filter(filter)

    @command.skill_level('administrator')
    def do_modgroup(self, context, group_id, subcmd, prim_id, *args):
        """usage: modgroup <id> add <id> [after <id>|before <id>]
        modgroup <id> remove <id>"""
        if not cib_factory.is_cib_sane():
            return False
        if subcmd not in ("add", "remove"):
            common_err("modgroup subcommand %s unknown" % subcmd)
            return False
        after_before = None
        if args:
            if subcmd != 'add':
                context.fatal_error("Expected add (found %s)" % subcmd)
            if args[0] not in ("after", "before"):
                context.fatal_error("Expected after|before (found %s)" % args[0])
            if len(args) != 2:
                context.fatal_error("Expected 'after|before <id>' (%d arguments given)" %
                                    len(args))
            after_before = args[0]
            ref_member_id = args[1]
        g = cib_factory.find_object(group_id)
        if not g:
            context.fatal_error("group %s does not exist" % group_id)
        if not xmlutil.is_group(g.node):
            context.fatal_error("element %s is not a group" % group_id)
        children = xmlutil.get_rsc_children_ids(g.node)
        if after_before and ref_member_id not in children:
            context.fatal_error("%s is not member of %s" % (ref_member_id, group_id))
        if subcmd == "remove" and prim_id not in children:
            context.fatal_error("%s is not member of %s" % (prim_id, group_id))
        # done checking arguments
        # have a group and children
        if not after_before:
            after_before = "after"
            ref_member_id = children[-1]
        # just do the filter
        # (i wonder if this is a feature abuse?)
        if subcmd == "add":
            if after_before == "after":
                sed_s = r's/ %s( |$)/& %s /' % (ref_member_id, prim_id)
            else:
                sed_s = r's/ %s( |$)/ %s& /' % (ref_member_id, prim_id)
        else:
            sed_s = r's/ %s( |$)/ /' % prim_id
        l = (group_id,)
        set_obj = mkset_obj(*l)
        return set_obj.filter("sed -r '%s'" % sed_s)

    @command.skill_level('administrator')
    def do_edit(self, context, *args):
        "usage: edit [xml] [<id>...]"
        if not cib_factory.is_cib_sane():
            return False
        err_buf.buffer()  # keep error messages
        set_obj = mkset_obj(*args)
        err_buf.release()  # show them, but get an ack from the user
        return set_obj.edit()

    def _verify(self, set_obj_semantic, set_obj_all):
        rc1 = set_obj_all.verify()
        if user_prefs.check_frequency != "never":
            rc2 = set_obj_semantic.semantic_check(set_obj_all)
        else:
            rc2 = 0
        return rc1 and rc2 <= 1

    @command.skill_level('administrator')
    def do_verify(self, context):
        "usage: verify"
        if not cib_factory.is_cib_sane():
            return False
        set_obj_all = mkset_obj("xml")
        return self._verify(set_obj_all, set_obj_all)

    @command.skill_level('administrator')
    def do_save(self, context, *args):
        "usage: save [xml] <filename>"
        if not cib_factory.is_cib_sane():
            return False
        if args[0] == "xml":
            f = args[1]
            set_obj = mkset_obj("xml")
        else:
            f = args[0]
            set_obj = mkset_obj()
        return set_obj.save_to_file(f)

    @command.skill_level('administrator')
    def do_load(self, context, *args):
        "usage: load [xml] {replace|update} {<url>|<path>}"
        if not cib_factory.is_cib_sane():
            return False
        if args[0] == "xml":
            if len(args) != 3:
                context.fatal_error("Expected 3 arguments (%d given)" % len(args))
            url = args[2]
            method = args[1]
            xml = True
        else:
            if len(args) != 2:
                context.fatal_error("Expected 2 arguments (%d given)" % len(args))
            url = args[1]
            method = args[0]
            xml = False
        if method not in ("replace", "update"):
            context.fatal_error("Unknown method %s" % method)
        if method == "replace":
            if options.interactive and cib_factory.has_cib_changed():
                if not utils.ask("This operation will erase all changes. Do you want to proceed?"):
                    return False
            cib_factory.erase()
        if xml:
            set_obj = mkset_obj("xml")
        else:
            set_obj = mkset_obj()
        return set_obj.import_file(method, url)

    @command.skill_level('administrator')
    def do_graph(self, context, *args):
        "usage: graph [<gtype> [<file> [<img_format>]]]"
        if args and args[0] == "exportsettings":
            return utils.save_graphviz_file(vars.graphviz_user_file, vars.graph)
        if not cib_factory.is_cib_sane():
            return False
        rc, gtype, outf, ftype = ui_utils.graph_args(args)
        if not rc:
            return False
        rc, d = utils.load_graphviz_file(vars.graphviz_user_file)
        if rc and d:
            vars.graph = d
        set_obj = mkset_obj()
        if not outf:
            rc = set_obj.show_graph(gtype)
        elif gtype == ftype:
            rc = set_obj.save_graph(gtype, outf)
        else:
            rc = set_obj.graph_img(gtype, outf, ftype)
        return rc

    @command.skill_level('administrator')
    def do_delete(self, context, *args):
        "usage: delete <id> [<id>...]"
        if not cib_factory.is_cib_sane():
            return False
        return cib_factory.delete(*args)

    @command.name('default-timeouts')
    @command.alias('default_timeouts')
    def do_default_timeouts(self, context, *args):
        "usage: default-timeouts <id> [<id>...]"
        if not cib_factory.is_cib_sane():
            return False
        return cib_factory.default_timeouts(*args)

    @command.skill_level('administrator')
    def do_rename(self, context, old_id, new_id):
        "usage: rename <old_id> <new_id>"
        if not cib_factory.is_cib_sane():
            return False
        return cib_factory.rename(old_id, new_id)

    @command.skill_level('administrator')
    def do_erase(self, context, nodes=None):
        "usage: erase [nodes]"
        if not cib_factory.is_cib_sane():
            return False
        if nodes:
            if nodes != 'nodes':
                context.fatal_error("Expected 'nodes' (found '%s')" % (nodes))
            return cib_factory.erase_nodes()
        else:
            return cib_factory.erase()

    @command.skill_level('administrator')
    def do_refresh(self, context):
        "usage: refresh"
        if options.interactive and cib_factory.has_cib_changed():
            if not utils.ask("All changes will be dropped. Do you want to proceed?"):
                return
        cib_factory.refresh()

    @command.alias('simulate')
    def do_ptest(self, context, *args):
        "usage: ptest [nograph] [v...] [scores] [utilization] [actions]"
        if not cib_factory.is_cib_sane():
            return False
        # use ptest/crm_simulate depending on which command was
        # used
        user_prefs.ptest = vars.simulate_programs[context.get_command_name()]
        if not user_prefs.ptest:
            return False
        set_obj = mkset_obj("xml")
        return ui_utils.ptestlike(set_obj.ptest, 'vv', context.get_command_name(), args)

    @command.skill_level('administrator')
    @command.wait
    def do_commit(self, context, force=None):
        "usage: commit [force]"
        if force and force != "force":
            syntax_err((context.get_command_name(), force))
            return False
        if not cib_factory.is_cib_sane():
            return False
        if not cib_factory.has_cib_changed():
            common_info("apparently there is nothing to commit")
            common_info("try changing something first")
            return
        rc1 = True
        if not (force or utils.cibadmin_can_patch()):
            rc1 = cib_factory.is_current_cib_equal()
        rc2 = cib_factory.is_cib_empty() or \
            self._verify(mkset_obj("xml", "changed"), mkset_obj("xml"))
        if rc1 and rc2:
            return cib_factory.commit()
        if force or user_prefs.force:
            common_info("commit forced")
            return cib_factory.commit(force=True)
        if utils.ask("Do you still want to commit?"):
            return cib_factory.commit(force=True)
        return False

    @command.skill_level('administrator')
    def do_upgrade(self, context, force=None):
        "usage: upgrade [force]"
        if not cib_factory.is_cib_sane():
            return False
        if force and force != "force":
            syntax_err((context.get_command_name(), force))
            return False
        if user_prefs.force or force:
            return cib_factory.upgrade_cib_06to10(True)
        else:
            return cib_factory.upgrade_cib_06to10()

    @command.skill_level('administrator')
    def do_schema(self, context, schema_st=None):
        "usage: schema [<schema>]"
        if not cib_factory.is_cib_sane():
            return False
        if not schema_st:
            print cib_factory.get_schema()
            return True
        return cib_factory.change_schema(schema_st)

    def __conf_object(self, context, *args):
        "The configure object command."
        if not cib_factory.is_cib_sane():
            return False
        cmd = context.get_command_name()
        if cmd in vars.cib_cli_map.values() and \
                not cib_factory.is_elem_supported(cmd):
            common_err("%s not supported by the RNG schema" % cmd)
            return False
        f = lambda: cib_factory.create_object(context.get_command_name(), *args)
        return f()

    @command.skill_level('administrator')
    def do_node(self, context, *args):
        """usage: node <uname>[:<type>]
           [attributes <param>=<value> [<param>=<value>...]]
           [utilization <param>=<value> [<param>=<value>...]]"""
        return self.__conf_object(context.get_command_name(), *args)

    @command.skill_level('administrator')
    def do_primitive(self, context, *args):
        """usage: primitive <rsc> {[<class>:[<provider>:]]<type>|@<template>}
        [params <param>=<value> [<param>=<value>...]]
        [meta <attribute>=<value> [<attribute>=<value>...]]
        [utilization <attribute>=<value> [<attribute>=<value>...]]
        [operations id_spec
            [op op_type [<attribute>=<value>...] ...]]"""
        return self.__conf_object(context.get_command_name(), *args)

    @command.skill_level('administrator')
    def do_group(self, context, *args):
        """usage: group <name> <rsc> [<rsc>...]
        [params <param>=<value> [<param>=<value>...]]
        [meta <attribute>=<value> [<attribute>=<value>...]]"""
        return self.__conf_object(context.get_command_name(), *args)

    @command.skill_level('administrator')
    def do_clone(self, context, *args):
        """usage: clone <name> <rsc>
        [params <param>=<value> [<param>=<value>...]]
        [meta <attribute>=<value> [<attribute>=<value>...]]"""
        return self.__conf_object(context.get_command_name(), *args)

    @command.alias('master')
    @command.skill_level('administrator')
    def do_ms(self, context, *args):
        """usage: ms <name> <rsc>
        [params <param>=<value> [<param>=<value>...]]
        [meta <attribute>=<value> [<attribute>=<value>...]]"""
        return self.__conf_object(context.get_command_name(), *args)

    @command.skill_level('administrator')
    def do_rsc_template(self, context, *args):
        """usage: rsc_template <name> [<class>:[<provider>:]]<type>
        [params <param>=<value> [<param>=<value>...]]
        [meta <attribute>=<value> [<attribute>=<value>...]]
        [utilization <attribute>=<value> [<attribute>=<value>...]]
        [operations id_spec
            [op op_type [<attribute>=<value>...] ...]]"""
        return self.__conf_object(context.get_command_name(), *args)

    @command.skill_level('administrator')
    def do_location(self, context, *args):
        """usage: location <id> <rsc> {node_pref|rules}

        node_pref :: <score>: <node>

        rules ::
          rule [id_spec] [$role=<role>] <score>: <expression>
          [rule [id_spec] [$role=<role>] <score>: <expression> ...]

        id_spec :: $id=<id> | $id-ref=<id>
        score :: <number> | <attribute> | [-]inf
        expression :: <simple_exp> [bool_op <simple_exp> ...]
        bool_op :: or | and
        simple_exp :: <attribute> [type:]<binary_op> <value>
                      | <unary_op> <attribute>
                      | date <date_expr>
        type :: string | version | number
        binary_op :: lt | gt | lte | gte | eq | ne
        unary_op :: defined | not_defined"""
        return self.__conf_object(context.get_command_name(), *args)

    @command.alias('collocation')
    @command.skill_level('administrator')
    def do_colocation(self, context, *args):
        """usage: colocation <id> <score>: <rsc>[:<role>] <rsc>[:<role>] ...
        [node-attribute=<node_attr>]"""
        return self.__conf_object(context.get_command_name(), *args)

    @command.skill_level('administrator')
    def do_order(self, context, *args):
        """usage: order <id> {kind|<score>}: <rsc>[:<action>] <rsc>[:<action>] ...
        [symmetrical=<bool>]"""
        return self.__conf_object(context.get_command_name(), *args)

    @command.skill_level('administrator')
    def do_rsc_ticket(self, context, *args):
        """usage: rsc_ticket <id> <ticket_id>: <rsc>[:<role>] [<rsc>[:<role>] ...]
        [loss-policy=<loss_policy_action>]"""
        return self.__conf_object(context.get_command_name(), *args)

    @command.skill_level('administrator')
    def do_property(self, context, *args):
        "usage: property [$id=<set_id>] <option>=<value>"
        return self.__conf_object(context.get_command_name(), *args)

    @command.skill_level('administrator')
    def do_rsc_defaults(self, context, *args):
        "usage: rsc_defaults [$id=<set_id>] <option>=<value>"
        return self.__conf_object(context.get_command_name(), *args)

    @command.skill_level('administrator')
    def do_op_defaults(self, context, *args):
        "usage: op_defaults [$id=<set_id>] <option>=<value>"
        return self.__conf_object(context.get_command_name(), *args)

    @command.skill_level('administrator')
    def do_fencing_topology(self, context, *args):
        "usage: fencing_topology [<node>:] stonith_resources [stonith_resources ...]"
        return self.__conf_object(context.get_command_name(), *args)

    @command.skill_level('administrator')
    def do_xml(self, context, *args):
        "usage: xml <xml>"
        return self.__conf_object(context.get_command_name(), *args)

    @command.skill_level('administrator')
    def do_monitor(self, context, *args):
        "usage: monitor <rsc>[:<role>] <interval>[:<timeout>]"
        return self.__conf_object(context.get_command_name(), *args)

    @command.skill_level('expert')
    def do_user(self, context, *args):
        """user <uid> {roles|rules}

        roles :: role:<role-ref> [role:<role-ref> ...]
        rules :: rule [rule ...]

        (See the role command for details on rules.)"""
        return self.__conf_object(context.get_command_name(), *args)

    @command.skill_level('expert')
    def do_role(self, context, *args):
        """role <role-id> rule [rule ...]

        rule :: acl-right cib-spec [attribute:<attribute>]

        acl-right :: read | write | deny

        cib-spec :: xpath-spec | tag-ref-spec
        xpath-spec :: xpath:<xpath> | shortcut
        tag-ref-spec :: tag:<tag> | ref:<id> | tag:<tag> ref:<id>

        shortcut :: meta:<rsc>[:<attr>]
                    params:<rsc>[:<attr>]
                    utilization:<rsc>
                    location:<rsc>
                    property[:<attr>]
                    node[:<node>]
                    nodeattr[:<attr>]
                    nodeutil[:<node>]
                    status"""
        return self.__conf_object(context.get_command_name(), *args)

    @command.skill_level('expert')
    def do_rsctest(self, context, *args):
        "usage: rsctest <rsc_id> [<rsc_id> ...] [<node_id> ...]"
        if not cib_factory.is_cib_sane():
            return False
        rc = True
        rsc_l = []
        node_l = []
        current = "r"
        for id in args:
            el = cib_factory.find_object(id)
            if not el:
                common_err("element %s does not exist" % id)
                rc = False
            elif current == "r" and xmlutil.is_resource(el.node):
                if xmlutil.is_container(el.node):
                    rsc_l += el.node.findall("primitive")
                else:
                    rsc_l.append(el.node)
            elif xmlutil.is_normal_node(el.node):
                current = "n"
                node_l.append(el.node.get("uname"))
            else:
                syntax_err((context.get_command_name(), id), context='rsctest')
                return False
        if not rc:
            return False
        if not rsc_l:
            common_err("specify at least one resource")
            return False
        all_nodes = cib_factory.node_id_list()
        if not node_l:
            node_l = all_nodes
        return rsctest.test_resources(rsc_l, node_l, all_nodes)

    def should_wait(self):
        return cib_factory.has_cib_changed()

    def end_game(self, no_questions_asked=False):
        if cib_factory.has_cib_changed():
            if no_questions_asked or not options.interactive:
                self.commit("commit")
            elif utils.ask("There are changes pending. Do you want to commit them?"):
                self.commit("commit")
        cib_factory.reset()


user_prefs = UserPrefs.getInstance()
options = Options.getInstance()
err_buf = ErrorBuffer.getInstance()
cib_factory = CibFactory.getInstance()
